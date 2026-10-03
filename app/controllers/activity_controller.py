"""The activity history of a business, and its live notifications.

Every product change, received message, and connection event is recorded for each business it
concerns, from that business's point of view ("You added…", "Acme accepted your request").
It is saved in Firestore (the history, filterable by kind and date) and pushed to the Realtime
Database (live/{businessId}/activity): the notification bell shows it, and open pages (Network,
Messages, a business's page in the directory) refresh the moment it arrives.
"""

import logging

from google.cloud import firestore
from google.cloud.firestore import Client, FieldFilter

from app.controllers import crud
from app.core import realtime
from app.dependencies.business_access import BusinessAccess
from app.models.activity import Activity, activity_collection
from app.schemas.enums import ActivityCategory
from app.utils.helpers import current_time_ms

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 300  # the most entries one page of history shows


def record(
    db: Client,
    business_id: str,
    category: ActivityCategory,
    action: str,
    title: str,
    *,
    by: BusinessAccess,
    detail: str = "",
    link: str = "",
) -> None:
    """Adds an entry to a business's history and notifies it live.

    by: who did it. For their own business the person is named; for another business, their business is.
    Never fails the change that caused it: a problem here is only logged."""
    try:
        ref = activity_collection(db, business_id).document()
        now = current_time_ms()
        own = by.business_id == business_id
        person = by.member.display_name or by.user.name or by.user.email or ""
        activity = Activity(
            id=ref.id,
            category=category,
            action=action,
            title=title,
            detail=detail[:300],
            link=link,
            actor_uid=by.user.uid if own else "",
            actor_name=person if own else by.business.business_name,
            created_at=now,
            updated_at=now,
        )
        ref.set(activity.to_firestore())
        # The live copy is encrypted with the feed's key, which the business's members get (see chat access)
        live = f"{realtime.live_path(business_id)}/{ref.id}"
        realtime.get_store().set(live, realtime.seal(live, activity.model_dump(mode="json", by_alias=True, exclude={"id"})))
    except Exception:
        logger.exception("Could not record activity %s for business %s", action, business_id)


def list_activity(
    db: Client,
    access: BusinessAccess,
    category: ActivityCategory | None = None,
    start: int | None = None,
    end: int | None = None,
) -> list[Activity]:
    """The history, newest first. start / end: milliseconds (the browser turns the chosen days into
    its own local midnight), so "today" means the user's today."""
    # The first time: add what happened before the history existed (products, connections, messages)
    from app.controllers.activity_backfill import ensure_backfilled

    ensure_backfilled(db, access.business_id)
    query = activity_collection(db, access.business_id)
    if category:
        query = query.where(filter=FieldFilter("category", "==", category.value))
    ranged = query
    if start is not None:
        ranged = ranged.where(filter=FieldFilter("createdAt", ">=", start))
    if end is not None:
        ranged = ranged.where(filter=FieldFilter("createdAt", "<=", end))
    newest = ranged.order_by("createdAt", direction=firestore.Query.DESCENDING).limit(HISTORY_LIMIT)

    # Without the index (firestore.indexes.json), read the kind and filter the dates here
    entries = [Activity.from_snapshot(snapshot) for snapshot in crud.stream_indexed(newest, fallback=query)]
    entries = [a for a in entries if (start is None or a.created_at >= start) and (end is None or a.created_at <= end)]
    return sorted(entries, key=lambda a: a.created_at, reverse=True)[:HISTORY_LIMIT]


def role_text(role) -> str:
    """SUPPLIER -> "supplier", AUTHORIZED_DEALER -> "authorized dealer"."""
    return str(getattr(role, "value", role)).replace("_", " ").lower()
