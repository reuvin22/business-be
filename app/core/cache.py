"""Redis cache in front of Firestore.

How it works ("cache-aside" with version numbers):

- Reading: look in Redis first. On a miss, read Firestore and save the result in Redis.
- Writing: we don't hunt down and delete every cached key. Each cached key contains a
  VERSION NUMBER for its scope, and a write simply bumps that number. Old entries are then
  never read again, and Redis removes them when they expire (CACHE_TTL_SECONDS).

Scopes (what one version number covers):
    business:{id}   everything under businesses/{id}, plus that business's orders,
                    relationships, conversations, and verification requests
    user:{uid}      the list of businesses a user belongs to
    conversation:{id}  one conversation and its messages
    directory       directory search results
    categories      the shared category tree
    admin           admin-only lists

Writes to /api/v1/businesses/{id}/... bump business:{id} automatically (middleware in main.py).
Writes that also affect ANOTHER business (e.g. an order changes both buyer and seller)
bump that business in the controller.

If Redis is not configured or is down, everything still works: reads go straight to Firestore.
"""

import json
import logging
import time
from collections.abc import Callable
from typing import TypeVar

import redis
from pydantic import BaseModel
from redis.backoff import NoBackoff
from redis.retry import Retry

from app.core.config import settings

logger = logging.getLogger(__name__)

KEY_PREFIX = "mb"
DIRECTORY = "directory"
CATEGORIES = "categories"
ADMIN = "admin"

# When Redis stops answering, skip it for this long and use Firestore directly
OFFLINE_PAUSE_SECONDS = 30

T = TypeVar("T")
M = TypeVar("M", bound=BaseModel)
_client: redis.Redis | None = None
_offline_until = 0.0  # time.monotonic() value; while in the future, Redis is skipped
_was_offline = False


def get_client() -> redis.Redis | None:
    """The shared Redis connection pool, or None when REDIS_URL is not set."""
    global _client
    if not settings.redis_url:
        return None
    if _client is None:
        _client = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=1,  # never let a slow cache make a request slower than the database
            socket_connect_timeout=1,
            retry=Retry(NoBackoff(), 0),  # don't retry: on a failure, go straight to Firestore
            health_check_interval=30,
        )
    return _client


def set_client(client: redis.Redis | None) -> None:
    """Replace the Redis client (tests use a fake in-memory Redis)."""
    global _client, _offline_until, _was_offline
    _client = client
    _offline_until = 0.0
    _was_offline = False


def _usable_client() -> redis.Redis | None:
    """The Redis client, or None while it is paused after a failure.

    After an outage, everything cached before it is thrown away (the "epoch" goes up),
    because changes made during the outage could not mark the cache as outdated.
    """
    global _was_offline
    if time.monotonic() < _offline_until:
        return None
    client = get_client()
    if client is not None and _was_offline:
        try:
            client.incr(EPOCH_KEY)
            _was_offline = False
        except redis.RedisError as error:
            _pause(error)
            return None
    return client


def _pause(error: Exception) -> None:
    global _offline_until, _was_offline
    _offline_until = time.monotonic() + OFFLINE_PAUSE_SECONDS
    _was_offline = True
    logger.warning("Redis is not reachable (%s). Using Firestore only for %s seconds.", error, OFFLINE_PAUSE_SECONDS)


# ---- Scopes ------------------------------------------------------------------------------


def business_scope(business_id: str) -> str:
    return f"business:{business_id}"


def user_scope(uid: str) -> str:
    return f"user:{uid}"


def conversation_scope(conversation_id: str) -> str:
    return f"conversation:{conversation_id}"


def collection_path(collection) -> str:
    """The path of a Firestore collection, e.g. businesses/abc/products."""
    return f"{collection.parent.path}/{collection.id}" if collection.parent else collection.id


def scope_for_path(path: str) -> str:
    """The scope of a Firestore path, e.g. "businesses/abc/products" -> "business:abc"."""
    parts = path.split("/")
    if parts[0] == "businesses" and len(parts) >= 2:
        return business_scope(parts[1])
    if parts[0] == "conversations" and len(parts) >= 2:
        return conversation_scope(parts[1])
    if parts[0] == "categories":
        return CATEGORIES
    return ADMIN


# ---- Reading and writing -----------------------------------------------------------------


EPOCH_KEY = f"{KEY_PREFIX}:epoch"  # goes up to throw away the whole cache at once


def _version_key(scope: str) -> str:
    return f"{KEY_PREFIX}:version:{scope}"


def bump(*scopes: str) -> None:
    """Marks everything cached in these scopes as outdated. Call after changing data."""
    client = _usable_client()
    if client is None or not scopes:
        return
    try:
        pipe = client.pipeline(transaction=False)
        for scope in set(scopes):
            pipe.incr(_version_key(scope))
        pipe.execute()
    except redis.RedisError as error:
        _pause(error)


def remember(
    scope: str, key: str, load: Callable[[], T], to_json: Callable[[T], object], from_json: Callable[[object], T]
) -> T:
    """Returns the cached value, or runs `load()` and caches its result."""
    client = _usable_client()
    if client is None:
        return load()

    try:
        # One round trip for both numbers that make up the key
        epoch, version = client.mget(EPOCH_KEY, _version_key(scope))
        cache_key = f"{KEY_PREFIX}:e{epoch or 0}:{scope}:v{version or 0}:{key}"
        cached = client.get(cache_key)
        if cached is not None:
            return from_json(json.loads(cached))
    except redis.RedisError as error:
        _pause(error)
        return load()
    except ValueError as error:  # an unreadable entry: ignore it and read the database
        logger.warning("Ignoring a bad cache entry (%s).", error)

    value = load()
    try:
        client.set(cache_key, json.dumps(to_json(value)), ex=settings.cache_ttl_seconds)
    except redis.RedisError as error:
        _pause(error)
    return value


# ---- Helpers for Pydantic models (what almost everything in this app is) -----------------


def cached_model(scope: str, key: str, model_class: type[M], load: Callable[[], M | None]) -> M | None:
    """One model (or None, e.g. a document that does not exist)."""
    return remember(
        scope,
        key,
        load,
        to_json=lambda model: model.model_dump(mode="json", by_alias=True) if model is not None else None,
        from_json=lambda data: model_class.model_validate(data) if data is not None else None,
    )


def cached_models(scope: str, key: str, model_class: type[M], load: Callable[[], list[M]]) -> list[M]:
    """A list of models."""
    return remember(
        scope,
        key,
        load,
        to_json=lambda models: [model.model_dump(mode="json", by_alias=True) for model in models],
        from_json=lambda data: [model_class.model_validate(item) for item in data],
    )
