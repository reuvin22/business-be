"""The activity from before the activity history existed, rebuilt once per business from what was saved:

- products: when each was added (createdAt) and last changed (updatedAt). Deleted products left nothing.
- connections: when each was requested, accepted or declined, and ended or withdrawn.
- messages: every message another business sent (from the Realtime Database, or Firestore for older chats).

The entries get fixed ids ("past-..."), so running it again changes nothing, and they are not pushed live
(they are history, not news). A marker (settings/activityBackfill) makes it run only once per business.
"""

import logging

from google.cloud.firestore import Client, FieldFilter

from app.core import realtime
from app.models.activity import Activity, activity_collection
from app.models.business import business_document
from app.models.network import (
    Conversation,
    Message,
    Relationship,
    conversations_collection,
    messages_collection,
    relationships_collection,
)
from app.models.product import Product, products_collection
from app.models.settings import settings_document
from app.schemas.enums import ActivityCategory, RelationshipStatus
from app.utils.helpers import current_time_ms

logger = logging.getLogger(__name__)

MARKER = "activityBackfill"
EDITED_AFTER_MS = 60_000  # a product saved more than a minute after it was added counts as edited
BATCH_SIZE = 400  # Firestore takes at most 500 writes per batch

_done: set[str] = set()  # businesses this server already checked (saves a read on every visit)


def ensure_backfilled(db: Client, business_id: str) -> None:
    """Rebuilds the business's past activity the first time its history is opened. Never fails the page."""
    if business_id in _done:
        return
    try:
        marker = settings_document(db, business_id, MARKER)
        if not marker.get().exists:
            # Only what came before the first entry the live history recorded (no double entries)
            first_live = _first_live_entry_at(db, business_id)
            entries = [e for e in past_activity(db, business_id) if first_live is None or e.created_at < first_live]
            _save(db, business_id, entries)
            marker.set({"doneAt": current_time_ms(), "entries": len(entries)})
            logger.info("Rebuilt %s past activity entries for business %s", len(entries), business_id)
        _done.add(business_id)
    except Exception:
        logger.exception("Could not rebuild the past activity of business %s (will try again)", business_id)


def _first_live_entry_at(db: Client, business_id: str) -> int | None:
    oldest = activity_collection(db, business_id).order_by("createdAt").limit(1).stream()
    return next((snapshot.to_dict().get("createdAt") for snapshot in oldest), None)


def past_activity(db: Client, business_id: str) -> list[Activity]:
    snapshot = business_document(db, business_id).get()
    my_name = (snapshot.to_dict() or {}).get("businessName", "") if snapshot.exists else ""
    return [*_products(db, business_id, my_name), *_connections(db, business_id), *_messages(db, business_id)]


def _entry(
    key: str,
    category: ActivityCategory,
    action: str,
    title: str,
    at: int,
    *,
    actor: str = "",
    detail: str = "",
    link: str = "",
) -> Activity:
    return Activity(
        id=f"past-{key}",
        category=category,
        action=action,
        title=title,
        detail=detail[:300],
        link=link,
        actor_uid="",
        actor_name=actor,
        created_at=at,
        updated_at=at,
    )


def _products(db: Client, business_id: str, my_name: str) -> list[Activity]:
    entries = []
    for snapshot in products_collection(db, business_id).stream():
        product = Product.from_snapshot(snapshot)
        link = f"/products/{product.id}"
        name = product.product_name
        if product.created_at:
            entries.append(
                _entry(
                    f"product-created-{product.id}",
                    ActivityCategory.PRODUCTS,
                    "product.created",
                    f"Product added: {name}",
                    product.created_at,
                    actor=my_name,
                    link=link,
                )
            )
        if product.updated_at and product.updated_at - product.created_at > EDITED_AFTER_MS:
            entries.append(
                _entry(
                    f"product-updated-{product.id}",
                    ActivityCategory.PRODUCTS,
                    "product.updated",
                    f"Product updated: {name}",
                    product.updated_at,
                    actor=my_name,
                    link=link,
                )
            )
    return entries


def _connections(db: Client, business_id: str) -> list[Activity]:
    # Imported here: relationship_controller records new activity, so it imports the activity code itself
    from app.controllers.activity_controller import role_text
    from app.controllers.relationship_controller import OPPOSITE_ROLE

    mine = FieldFilter("businessIds", "array_contains", business_id)
    entries = []
    for snapshot in relationships_collection(db).where(filter=mine).stream():
        r = Relationship.from_snapshot(snapshot)
        i_asked = r.business_id == business_id
        me = r.business_name if i_asked else r.related_business_name
        other = r.related_business_name if i_asked else r.business_name
        role = role_text(r.relationship_type if i_asked else OPPOSITE_ROLE[r.relationship_type])

        def add(change: str, at: int | None, mine_text: str, theirs_text: str, done_by_me: bool) -> None:
            if not at:
                return
            entries.append(
                _entry(
                    f"connection-{change}-{r.id}",
                    ActivityCategory.CONNECTIONS,
                    f"connection.{change}",
                    mine_text if done_by_me else theirs_text,
                    at,
                    actor=me if done_by_me else other,
                    detail=r.notes if change == "requested" else "",
                    link="/network",
                )
            )

        # The business that asked made the request; the one that was asked accepted or declined it
        add(
            "requested",
            r.created_at,
            f"You asked {other} to connect as your {role}",
            f"{other} wants to connect. They would be your {role}.",
            i_asked,
        )
        if r.started_at:
            add(
                "accepted",
                r.started_at,
                f"You accepted {other}'s request. You are now connected.",
                f"{other} accepted your request. They are now your {role}.",
                not i_asked,
            )
        if r.status == RelationshipStatus.DECLINED:
            add("declined", r.updated_at, f"You declined {other}'s request", f"{other} declined your request", not i_asked)
        if r.status == RelationshipStatus.ENDED and r.ended_at:
            if r.started_at:  # who ended it was not saved
                ended = f"The connection with {other} ended"
                add("ended", r.ended_at, ended, ended, True)
            else:
                add(
                    "withdrawn",
                    r.ended_at,
                    f"You withdrew your request to {other}",
                    f"{other} withdrew their request to connect",
                    i_asked,
                )
    return entries


def _messages(db: Client, business_id: str) -> list[Activity]:
    mine = FieldFilter("businessIds", "array_contains", business_id)
    entries = []
    for snapshot in conversations_collection(db).where(filter=mine).stream():
        conversation = Conversation.from_snapshot(snapshot)
        other_id = next((b for b in conversation.business_ids if b != business_id), "")
        other = conversation.business_names.get(other_id, "another business")

        # (id, text, sender, when) of each message the other business sent
        live = realtime.get_store().get(f"{realtime.dm_path(conversation.id)}/messages") or {}
        if live:
            received = [
                (key, m.get("message", ""), m.get("senderName", ""), m.get("createdAt", 0))
                for key, m in live.items()
                if m.get("senderBusinessId") == other_id
            ]
        else:  # a chat from before the Realtime Database: still in Firestore
            older = [Message.from_snapshot(s) for s in messages_collection(db, conversation.id).stream()]
            received = [(m.id, m.message, m.sender_name, m.created_at) for m in older if m.sender_business_id == other_id]

        for key, text, sender, at in received:
            entries.append(
                _entry(
                    f"message-{conversation.id}-{key}",
                    ActivityCategory.MESSAGES,
                    "message.received",
                    f"New message from {other}",
                    at,
                    actor=sender or other,
                    detail=text,
                    link=f"/messages?c={conversation.id}",
                )
            )
    return entries


def _save(db: Client, business_id: str, entries: list[Activity]) -> None:
    collection = activity_collection(db, business_id)
    for start in range(0, len(entries), BATCH_SIZE):
        batch = db.batch()
        for entry in entries[start : start + BATCH_SIZE]:
            batch.set(collection.document(entry.id), entry.to_firestore())
        batch.commit()
