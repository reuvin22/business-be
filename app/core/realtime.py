"""Firebase Realtime Database: the live chat (direct messages, the team channel, the market channel).

Only the API writes here (the Admin SDK ignores the rules). Browsers only LISTEN, and
database.rules.json decides what each signed-in user may read. Those rules cannot look at
Firestore, so the API keeps a small list of who may read which business's chats (chatAccess).

Layout:
  chatAccess/{uid}/{businessId}: true          this user may read that business's chats
  chat/team/{businessId}/messages/{id}         a business's own team channel (members only)
  chat/market/messages/{id}                    the public market channel (every signed-in user)
  chat/dm/{conversationId}/meta                {a, b: the two business ids, lastReadAt: {businessId: ms}}
  chat/dm/{conversationId}/messages/{id}       a conversation between two businesses
  live/{businessId}/activity/{id}              a business's activity, live (notifications; history is in Firestore)
  notificationSeen/{uid}/{businessId}          when this user last opened the notifications (the browser writes it)

Messages are ordered by their createdAt field (indexed in the rules).

What is said is encrypted (see `seal`): the text, photos, and order card of a message, and the title and
detail of an activity. Each room (a team channel, the market, a conversation, a live feed) has its own key;
the API gives it only to users who may read that room, and the browser decrypts with it.
"""

import itertools
import logging
from typing import Protocol

from firebase_admin import db as firebase_db
from firebase_admin import exceptions as firebase_exceptions

from app.core import crypto
from app.core.firebase import get_firebase_app

MESSAGE_LIMIT = 200  # how many of the newest messages a chat shows

logger = logging.getLogger(__name__)


def access_path(uid: str, business_id: str) -> str:
    return f"chatAccess/{uid}/{business_id}"


def team_path(business_id: str) -> str:
    return f"chat/team/{business_id}/messages"


MARKET_PATH = "chat/market/messages"


def dm_path(conversation_id: str) -> str:
    return f"chat/dm/{conversation_id}"


def live_path(business_id: str) -> str:
    """A business's live activity feed (notifications), read by its members like its chats."""
    return f"live/{business_id}/activity"


# ---- Encryption of what is said ---------------------------------------------------------------

# The fields that hold what was said; everything else (who, when) stays readable for the rules and sorting
SECRET_FIELDS = ("message", "attachments", "order", "title", "detail")


def room_of(path: str) -> str:
    """The room a path belongs to, e.g. chat/dm/abc/messages/m1 -> chat/dm/abc. Each room has its own key."""
    parts = path.strip("/").split("/")
    if parts[:2] == ["chat", "market"]:
        return "chat/market"
    if parts[0] == "chat" and len(parts) >= 3 and parts[1] in ("team", "dm"):
        return "/".join(parts[:3])
    if parts[0] == "live" and len(parts) >= 2:
        return "/".join(parts[:2])
    raise ValueError(f"No encryption room for {path}")


def room_key(path: str) -> str:
    """The key (base64) the browser decrypts this room's messages with. Only give it to who may read the room."""
    return crypto.room_key(room_of(path))


def seal(path: str, data: dict) -> dict:
    """A message (or activity) ready to save at path: what was said is encrypted with the room's key."""
    room = room_of(path)
    return {**data, **{k: crypto.seal_for_room(room, data[k]) for k in SECRET_FIELDS if data.get(k) is not None}}


def unseal(path: str, data: dict) -> dict:
    """The message as it was before `seal` (messages saved before encryption are returned as they are)."""
    room = room_of(path)
    return {**data, **{k: crypto.open_for_room(room, data[k]) for k in SECRET_FIELDS if k in data}}


def newest_messages(path: str, limit: int = MESSAGE_LIMIT) -> list[dict]:
    """The newest messages at path, oldest first, decrypted."""
    return [unseal(path, message) for message in get_store().newest(path, limit)]


# ---- Storage (the real database, or an in-memory one in tests) ------------------------------


class Store(Protocol):
    def get(self, path: str): ...
    def set(self, path: str, value) -> None: ...
    def update(self, path: str, values: dict) -> None: ...
    def push(self, path: str, value: dict) -> str: ...
    def delete(self, path: str) -> None: ...
    def newest(self, path: str, limit: int) -> list[dict]: ...


class FirebaseStore:
    """The Firebase Realtime Database (its address is FIREBASE_DATABASE_URL)."""

    def _ref(self, path: str):
        return firebase_db.reference(path, app=get_firebase_app())

    def get(self, path: str):
        return self._ref(path).get()

    def set(self, path: str, value) -> None:
        self._ref(path).set(value)

    def update(self, path: str, values: dict) -> None:
        self._ref(path).update(values)

    def push(self, path: str, value: dict) -> str:
        return self._ref(path).push(value).key

    def delete(self, path: str) -> None:
        self._ref(path).delete()

    def newest(self, path: str, limit: int) -> list[dict]:
        try:
            found = self._ref(path).order_by_child("createdAt").limit_to_last(limit).get() or {}
        except firebase_exceptions.InvalidArgumentError:
            # The createdAt index (database.rules.json) is not deployed yet: read everything and sort here
            logger.warning("Realtime Database index missing on %s. Deploy database.rules.json.", path)
            found = self._ref(path).get() or {}
        return _sorted_messages(found)[-limit:]


class MemoryStore:
    """A stand-in for tests: the same calls, kept in a dict."""

    def __init__(self):
        self.data: dict = {}
        self._ids = itertools.count(1)

    def _parent(self, path: str, create: bool) -> tuple[dict | None, str]:
        *parents, last = path.split("/")
        node = self.data
        for part in parents:
            if part not in node:
                if not create:
                    return None, last
                node[part] = {}
            node = node[part]
        return node, last

    def get(self, path: str):
        node, last = self._parent(path, create=False)
        return None if node is None else node.get(last)

    def set(self, path: str, value) -> None:
        node, last = self._parent(path, create=True)
        node[last] = value

    def update(self, path: str, values: dict) -> None:
        for key, value in values.items():
            self.set(f"{path}/{key}", value)

    def push(self, path: str, value: dict) -> str:
        key = f"m{next(self._ids):08d}"
        self.set(f"{path}/{key}", value)
        return key

    def delete(self, path: str) -> None:
        node, last = self._parent(path, create=False)
        if node is not None:
            node.pop(last, None)

    def newest(self, path: str, limit: int) -> list[dict]:
        return _sorted_messages(self.get(path) or {})[-limit:]


def _sorted_messages(found: dict) -> list[dict]:
    """{id: message} -> [message with its id], oldest first."""
    messages = [{**value, "id": key} for key, value in found.items()]
    return sorted(messages, key=lambda m: m.get("createdAt", 0))


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = FirebaseStore()
    return _store


def set_store(store: Store | None) -> None:
    """Replace the database (tests use MemoryStore)."""
    global _store
    _store = store


# ---- Who may read a business's chats -------------------------------------------------------


def grant_access(uid: str, business_id: str) -> None:
    get_store().set(access_path(uid, business_id), True)


def revoke_access(uid: str, business_id: str) -> None:
    get_store().delete(access_path(uid, business_id))


def delete_team(business_id: str, member_uids: list[str]) -> None:
    """When a business is deleted: its team channel and live feed go, and its members lose access."""
    store = get_store()
    store.delete(f"chat/team/{business_id}")
    store.delete(f"live/{business_id}")
    for uid in member_uids:
        store.delete(access_path(uid, business_id))


def edit_message(path: str, uid: str, text: str, now: int) -> dict:
    """Changes the text of the message at path (chat/.../messages/{id}). Only its sender may.
    Returns the message as it is now. Raises LookupError / PermissionError / ValueError."""
    store = get_store()
    message = store.get(path)
    if not message:
        raise LookupError("Message")
    message = unseal(path, message)
    if message.get("senderUid") != uid:
        raise PermissionError("You can only edit your own messages")
    if not text.strip() and not message.get("attachments") and not message.get("order"):
        raise ValueError("A message needs some text (or delete it instead)")
    store.update(path, seal(path, {"message": text.strip(), "editedAt": now}))
    return {**message, "message": text.strip(), "editedAt": now}


def delete_message(path: str, uid: str, business_id: str = "", by_business: str = "") -> dict:
    """Deletes the message at path. Its sender may; so may its business when by_business is that business
    (a business taking back its own market post). Returns the deleted message."""
    store = get_store()
    message = store.get(path)
    if not message:
        raise LookupError("Message")
    own_business = bool(by_business) and message.get("businessId") == by_business
    if message.get("senderUid") != uid and not own_business:
        raise PermissionError("You can only delete your own messages")
    store.delete(path)
    return unseal(path, message)
