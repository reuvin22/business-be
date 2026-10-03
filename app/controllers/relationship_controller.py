"""Business-to-business relationships (section 22), e.g. "Acme is our SUPPLIER".

One business asks, the other accepts or declines. Either side can end it later.
"""

from google.cloud import firestore
from google.cloud.firestore import Client, FieldFilter

from app.controllers import activity_controller, crud
from app.controllers.business_controller import find_business
from app.controllers.crud import bad_request, not_found
from app.core import cache
from app.dependencies.business_access import BusinessAccess
from app.models.network import Relationship, relationships_collection
from app.schemas.enums import ActivityCategory, Permission, RelationshipStatus, RelationshipType
from app.schemas.network import RelationshipIn, RelationshipRespondIn, RelationshipView
from app.utils.helpers import current_time_ms

# If Acme is Sunrise's SUPPLIER, then Sunrise is Acme's CUSTOMER.
OPPOSITE_ROLE = {
    RelationshipType.SUPPLIER: RelationshipType.CUSTOMER,
    RelationshipType.CUSTOMER: RelationshipType.SUPPLIER,
    RelationshipType.MANUFACTURER: RelationshipType.CUSTOMER,
    RelationshipType.DISTRIBUTOR: RelationshipType.SUPPLIER,
    RelationshipType.RESELLER: RelationshipType.SUPPLIER,
    RelationshipType.AUTHORIZED_DEALER: RelationshipType.SUPPLIER,
    RelationshipType.PARTNER: RelationshipType.PARTNER,
}


def to_view(relationship: Relationship, my_business_id: str) -> RelationshipView:
    """Shows a relationship from one side's point of view."""
    i_asked = relationship.business_id == my_business_id
    return RelationshipView(
        id=relationship.id,
        other_business_id=relationship.related_business_id if i_asked else relationship.business_id,
        other_business_name=relationship.related_business_name if i_asked else relationship.business_name,
        their_role=relationship.relationship_type if i_asked else OPPOSITE_ROLE[relationship.relationship_type],
        direction="OUTGOING" if i_asked else "INCOMING",
        status=relationship.status,
        notes=relationship.notes,
        created_at=relationship.created_at,
        started_at=relationship.started_at,
        ended_at=relationship.ended_at,
    )


def _all_for(db: Client, business_id: str) -> list[Relationship]:
    def read() -> list[Relationship]:
        query = relationships_collection(db).where(filter=FieldFilter("businessIds", "array_contains", business_id))
        newest_first = query.order_by("createdAt", direction=firestore.Query.DESCENDING)
        relationships = [Relationship.from_snapshot(s) for s in crud.stream_indexed(newest_first, fallback=query)]
        return sorted(relationships, key=lambda r: r.created_at, reverse=True)

    return cache.cached_models(cache.business_scope(business_id), "relationships", Relationship, read)


def is_connected(db: Client, business_id: str, other_id: str) -> bool:
    """Do the two businesses have an active relationship (the other one accepted)?"""
    return any(
        r.status == RelationshipStatus.ACTIVE and other_id in r.business_ids for r in _all_for(db, business_id)
    )


def _save(db: Client, relationship: Relationship) -> None:
    """Saves the relationship and clears both businesses' cached lists."""
    relationships_collection(db).document(relationship.id).set(relationship.to_firestore())
    cache.bump(*[cache.business_scope(business_id) for business_id in relationship.business_ids])


def list_relationships(db: Client, access: BusinessAccess) -> list[RelationshipView]:
    return [to_view(r, access.business_id) for r in _all_for(db, access.business_id)]


def request_relationship(db: Client, access: BusinessAccess, relationship_in: RelationshipIn) -> RelationshipView:
    access.require(Permission.MANAGE_RELATIONSHIPS)
    other_id = relationship_in.related_business_id
    if other_id == access.business_id:
        raise bad_request("You cannot connect with your own business")
    other = find_business(db, other_id)
    if other is None:
        raise not_found("Business")

    for existing in _all_for(db, access.business_id):
        same_pair = other_id in existing.business_ids
        still_open = existing.status in (RelationshipStatus.PENDING, RelationshipStatus.ACTIVE)
        if same_pair and still_open and to_view(existing, access.business_id).their_role == relationship_in.relationship_type:
            raise bad_request("You already have this relationship (or a pending request) with them")

    now = current_time_ms()
    ref = relationships_collection(db).document()
    relationship = Relationship(
        id=ref.id,
        business_id=access.business_id,
        business_name=access.business.business_name,
        related_business_id=other.id,
        related_business_name=other.business_name,
        business_ids=[access.business_id, other.id],
        relationship_type=relationship_in.relationship_type,
        requested_by_uid=access.user.uid,
        notes=relationship_in.notes,
        created_at=now,
        updated_at=now,
    )
    _save(db, relationship)
    role = activity_controller.role_text(relationship.relationship_type)
    other_role = activity_controller.role_text(OPPOSITE_ROLE[relationship.relationship_type])
    _record(
        db,
        access,
        relationship,
        "requested",
        mine=f"You asked {other.business_name} to connect as your {role}",
        theirs=f"{access.business.business_name} wants to connect. They would be your {other_role}.",
        detail=relationship.notes,
    )
    return to_view(relationship, access.business_id)


def respond_to_relationship(
    db: Client, access: BusinessAccess, relationship_id: str, respond_in: RelationshipRespondIn
) -> RelationshipView:
    """The business that was asked accepts or declines."""
    access.require(Permission.MANAGE_RELATIONSHIPS)
    relationship = _get(db, access, relationship_id)
    if relationship.related_business_id != access.business_id:
        raise bad_request("Only the business that was asked can respond")
    if relationship.status != RelationshipStatus.PENDING:
        raise bad_request("This request was already answered")

    now = current_time_ms()
    relationship.status = RelationshipStatus.ACTIVE if respond_in.accept else RelationshipStatus.DECLINED
    relationship.started_at = now if respond_in.accept else None
    relationship.updated_at = now
    _save(db, relationship)
    asker = relationship.business_name
    if respond_in.accept:
        role = activity_controller.role_text(relationship.relationship_type)
        _record(
            db,
            access,
            relationship,
            "accepted",
            mine=f"You accepted {asker}'s request. You are now connected.",
            theirs=f"{access.business.business_name} accepted your request. They are now your {role}.",
        )
    else:
        _record(
            db,
            access,
            relationship,
            "declined",
            mine=f"You declined {asker}'s request",
            theirs=f"{access.business.business_name} declined your request",
        )
    return to_view(relationship, access.business_id)


def end_relationship(db: Client, access: BusinessAccess, relationship_id: str) -> RelationshipView:
    """Either side ends an active relationship, or the asker cancels a pending request."""
    access.require(Permission.MANAGE_RELATIONSHIPS)
    relationship = _get(db, access, relationship_id)
    if relationship.status not in (RelationshipStatus.PENDING, RelationshipStatus.ACTIVE):
        raise bad_request("This relationship has already ended")

    was_request = relationship.status == RelationshipStatus.PENDING
    now = current_time_ms()
    relationship.status = RelationshipStatus.ENDED
    relationship.ended_at = now
    relationship.updated_at = now
    _save(db, relationship)

    other_name = to_view(relationship, access.business_id).other_business_name
    me = access.business.business_name
    if was_request and relationship.business_id == access.business_id:
        _record(
            db,
            access,
            relationship,
            "withdrawn",
            mine=f"You withdrew your request to {other_name}",
            theirs=f"{me} withdrew their request to connect",
        )
    elif was_request:
        _record(
            db,
            access,
            relationship,
            "declined",
            mine=f"You declined {other_name}'s request",
            theirs=f"{me} declined your request",
        )
    else:
        _record(
            db,
            access,
            relationship,
            "ended",
            mine=f"You ended the connection with {other_name}",
            theirs=f"{me} ended the connection with you",
        )
    return to_view(relationship, access.business_id)


def _record(
    db: Client, access: BusinessAccess, relationship: Relationship, change: str, *, mine: str, theirs: str, detail: str = ""
) -> None:
    """Adds the change to both businesses' activity history, each from its own point of view."""
    other_id = next(b for b in relationship.business_ids if b != access.business_id)
    for business_id, title in ((access.business_id, mine), (other_id, theirs)):
        activity_controller.record(
            db,
            business_id,
            ActivityCategory.CONNECTIONS,
            f"connection.{change}",
            title,
            by=access,
            detail=detail,
            link="/network",
        )


def _get(db: Client, access: BusinessAccess, relationship_id: str) -> Relationship:
    snapshot = relationships_collection(db).document(relationship_id).get()  # fresh read: used before changes
    if not snapshot.exists:
        raise not_found("Relationship")
    relationship = Relationship.from_snapshot(snapshot)
    if access.business_id not in relationship.business_ids:
        raise not_found("Relationship")
    return relationship
