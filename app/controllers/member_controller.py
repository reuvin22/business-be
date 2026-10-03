from fastapi import HTTPException, status
from google.cloud.firestore import ArrayRemove, ArrayUnion, Client, Increment

from app.controllers import crud, invitation_controller
from app.controllers.crud import bad_request, forbidden
from app.core import cache, realtime
from app.core.firebase import find_user_by_email
from app.core.permissions import ROLE_PERMISSIONS
from app.dependencies.business_access import BusinessAccess
from app.models.business import business_document
from app.models.invitation import Invitation
from app.models.member import Member, members_collection
from app.schemas.enums import MemberRole, MemberStatus, Permission
from app.schemas.member import MemberAddIn, MemberUpdateIn
from app.utils.helpers import current_time_ms


# Only the owner may hand these out: they control the team itself, and where buyers send their money
OWNER_ONLY_GRANTS = {Permission.MANAGE_MEMBERS, Permission.MANAGE_PAYMENTS}


def check_can_grant(access: BusinessAccess, permissions: list[Permission]) -> None:
    """A member may only give others permissions they have themselves (and never the owner-only ones)."""
    if access.member.role == MemberRole.OWNER:
        return
    mine = set(access.member.permissions)
    refused = sorted(p.value for p in permissions if p not in mine or p in OWNER_ONLY_GRANTS)
    if refused:
        raise forbidden(f"Only the owner can give these permissions: {', '.join(refused)}")


def check_can_manage(access: BusinessAccess, member: Member) -> None:
    """A member may only change or remove someone who has no more power than they have."""
    if access.member.role == MemberRole.OWNER:
        return
    if member.role == MemberRole.OWNER or not set(member.permissions) <= set(access.member.permissions):
        raise forbidden("Only the owner can change this member: they have permissions you do not have")
    if set(member.permissions) & OWNER_ONLY_GRANTS:
        raise forbidden("Only the owner can change members who manage the team or payments")


def list_members(db: Client, access: BusinessAccess) -> list[Member]:
    return crud.list_documents(members_collection(db, access.business_id), Member, order_by="joinedAt")


def add_member(db: Client, access: BusinessAccess, member_in: MemberAddIn) -> Invitation:
    """Invites someone to the team. They join when they accept (nobody is added without saying yes)."""
    access.require(Permission.MANAGE_MEMBERS)
    if member_in.role == MemberRole.OWNER:
        raise bad_request("A business has only one owner")
    if member_in.role == MemberRole.SELLER:
        raise bad_request("Create seller accounts on the Sellers tab")
    permissions = member_in.permissions if member_in.permissions is not None else ROLE_PERMISSIONS[member_in.role]
    check_can_grant(access, permissions)

    account = find_user_by_email(member_in.email)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account uses that email. Ask them to sign up first.",
        )
    return invitation_controller.invite(db, access, account, member_in.role, permissions)


def update_member(db: Client, access: BusinessAccess, user_id: str, member_in: MemberUpdateIn) -> Member:
    access.require(Permission.MANAGE_MEMBERS)
    member = crud.get_document(members_collection(db, access.business_id), user_id, Member, "Member")

    if member.role == MemberRole.OWNER or member_in.role == MemberRole.OWNER:
        raise bad_request("The owner role cannot be given or changed")
    if member.role == MemberRole.SELLER or member_in.role == MemberRole.SELLER:
        raise bad_request("Seller accounts are managed on the Sellers tab")
    if user_id == access.user.uid:
        raise bad_request("You cannot change your own role")
    check_can_manage(access, member)
    check_can_grant(access, member_in.permissions)

    updated = Member(**{**member.model_dump(), **member_in.model_dump(), "updated_at": current_time_ms()})

    # Only ACTIVE members are listed in memberUids (used for "my businesses")
    member_uids_change = ArrayUnion([user_id]) if updated.status == MemberStatus.ACTIVE else ArrayRemove([user_id])
    if updated.status != MemberStatus.ACTIVE:
        # First, so they cannot read the chats anymore even if the rest fails (they get it back when active again)
        realtime.revoke_access(user_id, access.business_id)
        new_chat_keys(db, access.business_id)

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
    if not is_leaving:
        check_can_manage(access, member)

    realtime.revoke_access(user_id, access.business_id)  # first: no more reading the team's chats
    new_chat_keys(db, access.business_id)  # and keys they may have kept cannot read what is said from now on
    batch = db.batch()
    batch.delete(members_collection(db, access.business_id).document(user_id))
    batch.update(
        business_document(db, access.business_id),
        {"memberUids": ArrayRemove([user_id]), "sellerUids": ArrayRemove([user_id])},
    )
    batch.commit()
    _clear_cache(access.business_id, user_id)


def new_chat_keys(db: Client, business_id: str) -> None:
    """From now on the business's chats use a new key version (see app/core/realtime.py)."""
    business_document(db, business_id).update({"chatKeyVersion": Increment(1)})
    cache.bump(cache.business_scope(business_id))


def _clear_cache(business_id: str, user_id: str) -> None:
    """The team changed, and so did that person's "my businesses" list."""
    cache.bump(cache.business_scope(business_id), cache.user_scope(user_id))
