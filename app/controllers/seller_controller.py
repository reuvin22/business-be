"""Seller accounts for the selling app (my-business-pos).

The business creates the account (email + first password), so sellers do not sign up themselves.
Someone who already has an account is invited instead, and keeps sole control of their password.
A seller is saved as a member with the SELLER role, and can only use the selling app
(see get_pos_access in app/dependencies/business_access.py).
"""

from firebase_admin import auth
from google.cloud.firestore import ArrayRemove, ArrayUnion, Client, FieldFilter

from app.controllers import crud, invitation_controller
from app.controllers.crud import bad_request, forbidden, not_found
from app.controllers.member_controller import list_members
from app.core import cache
from app.core.firebase import create_account, find_user_by_email, set_account_name, set_account_password
from app.core.permissions import ROLE_PERMISSIONS
from app.dependencies.business_access import BusinessAccess
from app.models.business import business_document, businesses_collection
from app.models.member import Member, members_collection
from app.models.profile import locations_collection
from app.schemas.enums import MemberRole, MemberStatus, Permission
from app.schemas.pos import SellerCreateIn, SellerPasswordIn, SellerUpdateIn
from app.schemas.views import SellerAdded
from app.utils.helpers import current_time_ms


def list_sellers(db: Client, access: BusinessAccess) -> list[Member]:
    return [member for member in list_members(db, access) if member.role == MemberRole.SELLER]


def create_seller(db: Client, access: BusinessAccess, seller_in: SellerCreateIn) -> SellerAdded:
    """Creates the login and adds it to the business as a seller.

    If the email already has an account (e.g. they sell for another business too), that account is NOT
    taken over: the person gets an invitation to accept, and only they can ever change its password."""
    access.require(Permission.MANAGE_MEMBERS)
    _check_location(db, access.business_id, seller_in.location_id)

    existing = find_user_by_email(seller_in.email)
    if existing is not None:
        invitation = invitation_controller.invite(
            db,
            access,
            existing,
            MemberRole.SELLER,
            ROLE_PERMISSIONS[MemberRole.SELLER],
            location_id=seller_in.location_id,
            display_name=seller_in.display_name,
        )
        return SellerAdded(invited=True, invitation=invitation)

    try:
        account = create_account(seller_in.email, seller_in.password, seller_in.display_name)
    except auth.EmailAlreadyExistsError:
        raise bad_request("That email already has an account. Try again to send them an invitation.") from None

    member_ref = members_collection(db, access.business_id).document(account["uid"])

    now = current_time_ms()
    seller = Member(
        id=account["uid"],
        email=account["email"],
        display_name=seller_in.display_name,
        role=MemberRole.SELLER,
        permissions=ROLE_PERMISSIONS[MemberRole.SELLER],
        location_id=seller_in.location_id,
        account_managed=True,  # this business made the login, so it may reset its password
        joined_at=now,
        created_at=now,
        updated_at=now,
    )

    batch = db.batch()
    batch.set(member_ref, seller.to_firestore())
    batch.update(business_document(db, access.business_id), {"sellerUids": ArrayUnion([seller.id])})
    batch.commit()
    _clear_cache(access.business_id, seller.id)
    return SellerAdded(invited=False, member=seller)


def update_seller(db: Client, access: BusinessAccess, user_id: str, seller_in: SellerUpdateIn) -> Member:
    """Changes the name, the store, or suspends / re-activates the seller."""
    access.require(Permission.MANAGE_MEMBERS)
    seller = _get_seller(db, access.business_id, user_id)
    _check_location(db, access.business_id, seller_in.location_id)

    updated = Member(**{**seller.model_dump(), **seller_in.model_dump(), "updated_at": current_time_ms()})
    # Only ACTIVE sellers are listed in sellerUids (used for the selling app's business list)
    seller_uids_change = ArrayUnion([user_id]) if updated.status == MemberStatus.ACTIVE else ArrayRemove([user_id])

    batch = db.batch()
    batch.set(members_collection(db, access.business_id).document(user_id), updated.to_firestore())
    batch.update(business_document(db, access.business_id), {"sellerUids": seller_uids_change})
    batch.commit()
    if seller.display_name != updated.display_name:
        set_account_name(user_id, updated.display_name)
    _clear_cache(access.business_id, user_id)
    return updated


def set_password(db: Client, access: BusinessAccess, user_id: str, password_in: SellerPasswordIn) -> None:
    """Sets a new password, e.g. when the seller forgot theirs. Only works for seller accounts."""
    access.require(Permission.MANAGE_MEMBERS)
    seller = _get_seller(db, access.business_id, user_id)
    # Only a login this business made, and that belongs to no other business. Anyone else's password is
    # theirs alone (they can use "Forgot password" on the sign-in page).
    if not seller.account_managed:
        raise forbidden("This seller signed in with their own account. They can reset it with 'Forgot password'.")
    if _used_elsewhere(db, access.business_id, user_id):
        raise forbidden("This account is also used by another business. The seller can reset it with 'Forgot password'.")
    set_account_password(user_id, password_in.password)


def remove_seller(db: Client, access: BusinessAccess, user_id: str) -> None:
    """Removes the seller from the business. The login itself is kept (it may sell for another business)."""
    access.require(Permission.MANAGE_MEMBERS)
    _get_seller(db, access.business_id, user_id)

    batch = db.batch()
    batch.delete(members_collection(db, access.business_id).document(user_id))
    batch.update(business_document(db, access.business_id), {"sellerUids": ArrayRemove([user_id])})
    batch.commit()
    _clear_cache(access.business_id, user_id)


def _used_elsewhere(db: Client, business_id: str, uid: str) -> bool:
    """Is this login a member or seller of any other business?"""
    for field in ("memberUids", "sellerUids"):
        query = businesses_collection(db).where(filter=FieldFilter(field, "array_contains", uid))
        if any(snapshot.id != business_id for snapshot in query.stream()):
            return True
    return False


def _get_seller(db: Client, business_id: str, user_id: str) -> Member:
    member = crud.read_fresh(members_collection(db, business_id).document(user_id), Member)
    if member is None or member.role != MemberRole.SELLER:
        raise not_found("Seller")
    return member


def _check_location(db: Client, business_id: str, location_id: str | None) -> None:
    if location_id and not locations_collection(db, business_id).document(location_id).get().exists:
        raise not_found("Location")


def _clear_cache(business_id: str, user_id: str) -> None:
    cache.bump(cache.business_scope(business_id), cache.user_scope(user_id))
