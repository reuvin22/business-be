from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from google.cloud.firestore import Client

from app.core import cache
from app.core.firebase import get_db
from app.dependencies.auth import get_current_user
from app.models.business import Business, business_document
from app.models.member import Member, members_collection
from app.schemas.enums import MemberRole, MemberStatus, Permission
from app.schemas.user import CurrentUser
from app.utils.parallel import run_parallel


@dataclass
class BusinessAccess:
    """The business from the URL, plus who is using it and what they may do.

    Controllers get this instead of loose ids, so every check lives in one place:
        access.require(Permission.MANAGE_PRODUCTS)
    """

    business: Business
    member: Member
    user: CurrentUser

    @property
    def business_id(self) -> str:
        return self.business.id

    def can(self, permission: Permission) -> bool:
        return self.member.role == MemberRole.OWNER or permission in self.member.permissions

    def require(self, permission: Permission) -> None:
        """Stops the request with 403 when the member does not have this permission."""
        if not self.can(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You need the '{permission.value}' permission to do this",
            )


def get_business_access(
    business_id: str,
    db: Client = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> BusinessAccess:
    """Add this to any route with {business_id} in its URL. Only active members get through.

    Non-members get 404 (not 403), so they cannot tell whether the business exists.
    Seller accounts get 403: they may only use the selling app (see get_pos_access).
    """
    access = _load_access(db, business_id, user)
    if access.member.role == MemberRole.SELLER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Seller accounts can only use the selling app"
        )
    return access


def get_pos_access(
    business_id: str,
    db: Client = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> BusinessAccess:
    """For the selling app's routes (/businesses/{business_id}/pos/...). Sellers and any member
    with the 'pos.use' permission get through."""
    access = _load_access(db, business_id, user)
    access.require(Permission.USE_POS)
    return access


def _load_access(db: Client, business_id: str, user: CurrentUser) -> BusinessAccess:
    not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")

    # This runs on every business request, so both reads are cached (and read in parallel on a miss)
    business, member = run_parallel(
        lambda: load_business(db, business_id),
        lambda: cache.cached_model(
            cache.business_scope(business_id),
            f"member:{user.uid}",
            Member,
            lambda: _read_member(db, business_id, user.uid),
        ),
    )
    if business is None or member is None or member.status != MemberStatus.ACTIVE:
        raise not_found

    return BusinessAccess(business=business, member=member, user=user)


def load_business(db: Client, business_id: str) -> Business | None:
    """Any business by id (cached), or None."""

    def read() -> Business | None:
        snapshot = business_document(db, business_id).get()
        return Business.from_snapshot(snapshot) if snapshot.exists else None

    return cache.cached_model(cache.business_scope(business_id), "business", Business, read)


def _read_member(db: Client, business_id: str, uid: str) -> Member | None:
    snapshot = members_collection(db, business_id).document(uid).get()
    return Member.from_snapshot(snapshot) if snapshot.exists else None
