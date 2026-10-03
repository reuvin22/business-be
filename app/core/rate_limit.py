"""Limits how often one caller may use the API, so a script cannot flood a business with orders, messages, or
uploads, or slow the server down for everyone.

Each request counts against its caller: the signed-in account (a hash of the login token, so it is
the same on every server) or, without a login, the IP address. Counts are kept in Redis when it is set up
(shared by every server), or in memory otherwise. Over the limit, the API answers 429 Too Many Requests.
"""

import hashlib
import threading
import time
from dataclasses import dataclass

import redis

from app.core import cache


@dataclass(frozen=True)
class Limit:
    name: str
    requests: int
    seconds: int


# Checked in order; a request counts against every rule it matches (so uploads also count as writes)
READS = Limit("read", 600, 60)  # 10 a second on average: plenty for a busy screen
WRITES = Limit("write", 120, 60)  # saving, sending, ordering
UPLOADS = Limit("upload", 30, 60)
SIGN_IN_FREE = Limit("anonymous", 120, 60)  # requests without a login (health checks, webhooks)
# Pairing a phone scanner needs no login, only the till's one-time code: few tries, so codes cannot be guessed
PAIRING = Limit("pair", 10, 60)
# A paired phone scanner (its token): about one scan a second, with room for quick bursts
SCANNER = Limit("scanner", 90, 60)
# All phone scanners behind one network address (a shop's Wi-Fi may have a few): stops made-up tokens
SCANNERS_PER_ADDRESS = Limit("scanner-address", 360, 60)

# Expensive paths get their own, lower limits: (path contains, limit)
SPECIAL = [
    ("/images", UPLOADS),
]

_memory: dict[str, tuple[int, float]] = {}
_lock = threading.Lock()


def caller_key(authorization: str, client_ip: str, scanner_token: str = "") -> str:
    if authorization.lower().startswith("bearer "):
        return "u:" + hashlib.sha256(authorization[7:].encode()).hexdigest()[:24]
    if scanner_token:
        return "s:" + hashlib.sha256(scanner_token.encode()).hexdigest()[:24]
    return f"ip:{client_ip}"


def limits_for(method: str, path: str, signed_in: bool, scanner: bool = False) -> list[Limit]:
    if path.endswith("/pos/scanner/pair"):
        return [PAIRING, SIGN_IN_FREE]
    if scanner:
        return [SCANNER]
    if not signed_in:
        return [SIGN_IN_FREE]
    found = [READS if method in ("GET", "HEAD", "OPTIONS") else WRITES]
    found += [limit for part, limit in SPECIAL if part in path and method == "POST"]
    return found


def hit(caller: str, limit: Limit) -> int | None:
    """Counts one request. Returns None when allowed, or how many seconds to wait."""
    window = int(time.time() // limit.seconds)
    key = f"{cache.KEY_PREFIX}:rl:{limit.name}:{caller}:{window}"
    retry_after = limit.seconds - int(time.time() % limit.seconds)
    client = cache.get_client()
    if client is not None:
        try:
            pipe = client.pipeline()
            pipe.incr(key)
            pipe.expire(key, limit.seconds + 5)
            count = pipe.execute()[0]
            return retry_after if count > limit.requests else None
        except redis.RedisError:
            pass  # Redis is down: count in memory instead of letting everything through
    with _lock:
        if len(_memory) > 50_000:  # forget old windows
            now = time.time()
            for old in [k for k, (_, expires) in _memory.items() if expires < now]:
                _memory.pop(old, None)
        count, _ = _memory.get(key, (0, 0.0))
        _memory[key] = (count + 1, time.time() + limit.seconds)
    return retry_after if count + 1 > limit.requests else None


def reset() -> None:
    """Forget every count (tests)."""
    _memory.clear()


def use_quota(key: str, amount: int, limit: int, seconds: int) -> bool:
    """Adds `amount` to a running total (e.g. bytes uploaded today). False (and nothing added) when it would
    go over `limit`."""
    window = int(time.time() // seconds)
    full_key = f"{cache.KEY_PREFIX}:quota:{key}:{window}"
    client = cache.get_client()
    if client is not None:
        try:
            total = client.incrby(full_key, amount)
            client.expire(full_key, seconds + 60)
            if total > limit:
                client.decrby(full_key, amount)
                return False
            return True
        except redis.RedisError:
            pass
    with _lock:
        total, _ = _memory.get(full_key, (0, 0.0))
        if total + amount > limit:
            return False
        _memory[full_key] = (total + amount, time.time() + seconds)
    return True

