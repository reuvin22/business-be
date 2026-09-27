from fastapi import HTTPException, status
from google.cloud.firestore import ArrayRemove, ArrayUnion, Client

from app.controllers import crud
from app.controllers.crud import bad_request
from app.core import cache
from app.core.firebase import find_user_by_email
from app.core.permissions import ROLE_PERMISSIONS
from app.dependencies.business_access import BusinessAccess
from app.models.business import business_document
from app.models.member import Member, members_collection
from app.schemas.enums import MemberRole, MemberStatus, Permission
from app.schemas.member import MemberAddIn, MemberUpdateIn
from app.utils.helpers import current_time_ms


def list_members(db: Client, access: BusinessAccess) -> list[Member]:
    return crud.list_documents(members_collection(db, access.business_id), Member, order_by="joinedAt")


def add_member(db: Client, access: BusinessAccess, member_in: MemberAddIn) -> Member:
    access.require(Permission.MANAGE_MEMBERS)
    if member_in.role == MemberRole.OWNER:
        raise bad_request("A business has only one owner")

    account = find_user_by_email(member_in.email)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account uses that email. Ask them to sign up first.",
        )

    member_ref = members_collection(db, access.business_id).document(account["uid"])
    if member_ref.get().exists:
        raise bad_request("This person is already a member")

    now = current_time_ms()
    member = Member(
        id=account["uid"],
        email=account["email"],
        display_name=account["display_name"],
        role=member_in.role,
        permissions=member_in.permissions if member_in.permissions is not None else ROLE_PERMISSIONS[member_in.role],
        joined_at=now,
        created_at=now,
        updated_at=now,
    )

    batch = db.batch()
    batch.set(member_ref, member.to_firestore())
    batch.update(business_document(db, access.business_id), {"memberUids": ArrayUnion([member.id])})
    batch.commit()
    _clear_cache(access.business_id, member.id)
    return member


def update_member(db: Client, access: BusinessAccess, user_id: str, member_in: MemberUpdateIn) -> Member:
    access.require(Permission.MANAGE_MEMBERS)
    member = crud.get_document(members_collection(db, access.business_id), user_id, Member, "Member")

    if member.role == MemberRole.OWNER or member_in.role == MemberRole.OWNER:
        raise bad_request("The owner role cannot be given or changed")
    if user_id == access.user.uid:
        raise bad_request("You cannot change your own role")

    updated = Member(**{**member.model_dump(), **member_in.model_dump(), "updated_at": current_time_ms()})

    # Only ACTIVE members are listed in memberUids (used for "my businesses")
    member_uids_change = ArrayUnion([user_id]) if updated.status == MemberStatus.ACTIVE else ArrayRemove([user_id])

    batch = db.batch()
    batch.set(members_collection(db, access.business_id).document(user_id), updated.to_firestore())
    batch.update(business_document(db, access.business_id), {"memberUids": member_uids_change})
    batch.commit()
    _clear_cache(access.business_id, user_id)
    return updated


def remove_member(db: Client, access: BusinessAccess, user_id: str) -> None:
    """Removes someone from the team. Any member can remove themselves (leave the business)."""
    is_leaving = user_id == access.user.uid
    if not is_leaving:
        access.require(Permission.MANAGE_MEMBERS)

    member = crud.get_document(members_collection(db, access.business_id), user_id, Member, "Member")
    if member.role == MemberRole.OWNER:
        raise bad_request("The owner cannot leave or be removed. Delete the business instead.")

    batch = db.batch()
    batch.delete(members_collection(db, access.business_id).document(user_id))
    batch.update(business_document(db, access.business_id), {"memberUids": ArrayRemove([user_id])})
    batch.commit()
    _clear_cache(access.business_id, user_id)


def _clear_cache(business_id: str, user_id: str) -> None:
    """The team changed, and so did that person's "my businesses" list."""
    cache.bump(cache.business_scope(business_id), cache.user_scope(user_id))
