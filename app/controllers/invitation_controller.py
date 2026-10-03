"""Invitations to join a team. A business can only ADD people who say yes: adding a member, or a seller
whose email already has an account, sends an invitation that they accept (or decline) in SIRIS."""

from google.cloud.firestore import ArrayUnion, Client, FieldFilter

from app.controllers import crud
from app.controllers.crud import bad_request, forbidden, not_found
from app.core import cache
from app.dependencies.business_access import BusinessAccess, load_business
from app.models.business import business_document
from app.models.invitation import Invitation, invitation_id, invitations_collection
from app.models.member import Member, members_collection
from app.schemas.enums import BusinessStatus, MemberRole, MemberStatus, Permission
from app.schemas.user import CurrentUser
from app.utils.helpers import current_time_ms


def invite(
    db: Client,
    access: BusinessAccess,
    account: dict,
    role: MemberRole,
    permissions: list[Permission],
    location_id: str | None = None,
    display_name: str = "",
) -> Invitation:
    """Invites the account ({uid, email, display_name}) to the team."""
    uid = account["uid"]
    if members_collection(db, access.business_id).document(uid).get().exists:
        raise bad_request("This person is already on your team")
    ref = invitations_collection(db).document(invitation_id(access.business_id, uid))
    if ref.get().exists:
        raise bad_request("This person has already been invited")

    now = current_time_ms()
    invitation = Invitation(
        id=ref.id,
        business_id=access.business_id,
        business_name=access.business.business_name,
        business_logo=access.business.business_logo,
        uid=uid,
        email=account["email"],
        display_name=display_name or account["display_name"],
        role=role,
        permissions=permissions,
        location_id=location_id,
        invited_by_name=access.member.display_name or access.user.name or access.user.email or "",
        created_at=now,
        updated_at=now,
    )
    ref.set(invitation.to_firestore())
    cache.bump(cache.business_scope(access.business_id), cache.user_scope(uid))
    return invitation


def list_for_business(db: Client, access: BusinessAccess) -> list[Invitation]:
    """The business's invitations that are still waiting for an answer."""

    def read() -> list[Invitation]:
        query = invitations_collection(db).where(filter=FieldFilter("businessId", "==", access.business_id))
        return sorted((Invitation.from_snapshot(s) for s in query.stream()), key=lambda i: i.created_at)

    return cache.cached_models(cache.business_scope(access.business_id), "invitations", Invitation, read)


def cancel(db: Client, access: BusinessAccess, invite_id: str) -> None:
    access.require(Permission.MANAGE_MEMBERS)
    invitation = crud.read_fresh(invitations_collection(db).document(invite_id), Invitation)
    if invitation is None or invitation.business_id != access.business_id:
        raise not_found("Invitation")
    invitations_collection(db).document(invite_id).delete()
    cache.bump(cache.business_scope(access.business_id), cache.user_scope(invitation.uid))


# ---- The invited person ------------------------------------------------------------------------


def list_mine(db: Client, user: CurrentUser) -> list[Invitation]:
    def read() -> list[Invitation]:
        query = invitations_collection(db).where(filter=FieldFilter("uid", "==", user.uid))
        return sorted((Invitation.from_snapshot(s) for s in query.stream()), key=lambda i: i.created_at)

    return cache.cached_models(cache.user_scope(user.uid), "invitations", Invitation, read)


def _my_invitation(db: Client, user: CurrentUser, invite_id: str) -> Invitation:
    invitation = crud.read_fresh(invitations_collection(db).document(invite_id), Invitation)
    if invitation is None or invitation.uid != user.uid:
        raise not_found("Invitation")
    return invitation


def accept(db: Client, user: CurrentUser, invite_id: str) -> Member:
    """Joins the team with the role and permissions of the invitation."""
    invitation = _my_invitation(db, user, invite_id)
    business = load_business(db, invitation.business_id)
    if business is None or business.business_status != BusinessStatus.ACTIVE:
        invitations_collection(db).document(invite_id).delete()
        raise not_found("Business")
    if invitation.role == MemberRole.OWNER:
        raise forbidden("This invitation is not valid")

    now = current_time_ms()
    member = Member(
        id=user.uid,
        email=invitation.email or user.email or "",
        display_name=invitation.display_name or user.name or "",
        role=invitation.role,
        permissions=invitation.permissions,
        status=MemberStatus.ACTIVE,
        location_id=invitation.location_id,
        joined_at=now,
        created_at=now,
        updated_at=now,
    )
    uids_field = "sellerUids" if invitation.role == MemberRole.SELLER else "memberUids"
    batch = db.batch()
    batch.set(members_collection(db, invitation.business_id).document(user.uid), member.to_firestore())
    batch.update(business_document(db, invitation.business_id), {uids_field: ArrayUnion([user.uid])})
    batch.delete(invitations_collection(db).document(invite_id))
    batch.commit()
    cache.bump(cache.business_scope(invitation.business_id), cache.user_scope(user.uid))
    return member


def decline(db: Client, user: CurrentUser, invite_id: str) -> None:
    invitation = _my_invitation(db, user, invite_id)
    invitations_collection(db).document(invite_id).delete()
    cache.bump(cache.business_scope(invitation.business_id), cache.user_scope(user.uid))
