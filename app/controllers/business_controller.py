from google.cloud.firestore import Client, FieldFilter

from app.controllers.crud import forbidden
from app.core import cache
from app.core.permissions import ALL_PERMISSIONS
from app.dependencies.business_access import BusinessAccess, load_business
from app.models.business import Business, business_document, businesses_collection
from app.models.member import Member, members_collection
from app.schemas.business import BusinessIn, MyRole
from app.schemas.enums import MemberRole, Permission
from app.schemas.user import CurrentUser
from app.schemas.views import BusinessContext
from app.utils.helpers import current_time_ms


def list_my_businesses(db: Client, user: CurrentUser) -> list[Business]:
    """Businesses where the user is an active member."""

    def read() -> list[Business]:
        query = businesses_collection(db).where(filter=FieldFilter("memberUids", "array_contains", user.uid))
        businesses = [Business.from_snapshot(snapshot) for snapshot in query.stream()]
        return sorted(businesses, key=lambda business: business.created_at)

    return cache.cached_models(cache.user_scope(user.uid), "businesses", Business, read)


def create_business(db: Client, user: CurrentUser, business_in: BusinessIn) -> Business:
    """Creates the business and makes the user its OWNER."""
    now = current_time_ms()
    business_ref = businesses_collection(db).document()

    business = Business(
        **business_in.model_dump(),
        id=business_ref.id,
        created_at=now,
        updated_at=now,
        owner_uid=user.uid,
        member_uids=[user.uid],
    )
    owner = Member(
        id=user.uid,
        email=user.email or "",
        display_name=user.name or "",
        role=MemberRole.OWNER,
        permissions=ALL_PERMISSIONS,
        joined_at=now,
        created_at=now,
        updated_at=now,
    )

    # A batch saves both documents together: either both are saved or neither is.
    batch = db.batch()
    batch.set(business_ref, business.to_firestore())
    batch.set(members_collection(db, business.id).document(user.uid), owner.to_firestore())
    batch.commit()

    cache.bump(cache.user_scope(user.uid), cache.DIRECTORY)
    return business


def update_business(db: Client, access: BusinessAccess, business_in: BusinessIn) -> Business:
    access.require(Permission.EDIT_BUSINESS)
    now = current_time_ms()

    # update() only changes the form fields; system fields like ratings are left alone.
    changes = business_in.model_dump(mode="json", by_alias=True)
    changes["updatedAt"] = now
    business_document(db, access.business_id).update(changes)

    return Business(**{**access.business.model_dump(), **business_in.model_dump(), "updated_at": now})


def delete_business(db: Client, access: BusinessAccess) -> None:
    """Deletes the business and everything under it. Orders and messages with other businesses are kept."""
    if access.member.role != MemberRole.OWNER:
        raise forbidden("Only the owner can delete the business")
    # Firestore does not delete sub-collections on its own; recursive_delete does.
    db.recursive_delete(business_document(db, access.business_id))
    cache.bump(
        cache.business_scope(access.business_id),
        cache.DIRECTORY,
        *[cache.user_scope(uid) for uid in access.business.member_uids],
    )


def get_my_role(access: BusinessAccess) -> MyRole:
    permissions = ALL_PERMISSIONS if access.member.role == MemberRole.OWNER else access.member.permissions
    return MyRole(role=access.member.role, permissions=permissions)


def find_business(db: Client, business_id: str) -> Business | None:
    """Any business by id (no membership check, cached). Used when dealing with another business."""
    return load_business(db, business_id)


def get_context(access: BusinessAccess) -> BusinessContext:
    """The business and your role in it, in one response (what the business pages need first)."""
    return BusinessContext(business=access.business, role=get_my_role(access))
