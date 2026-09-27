from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from google.cloud.firestore import Client

from app.core.firebase import get_db
from app.dependencies.auth import get_current_user
from app.models.business import Business, business_document
from app.models.member import Member, members_collection
from app.schemas.enums import MemberRole, MemberStatus, Permission
from app.schemas.user import CurrentUser


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
    """
    not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")

    business_snapshot = business_document(db, business_id).get()
    if not business_snapshot.exists:
        raise not_found

    member_snapshot = members_collection(db, business_id).document(user.uid).get()
    if not member_snapshot.exists:
        raise not_found
    member = Member.from_snapshot(member_snapshot)
    if member.status != MemberStatus.ACTIVE:
        raise not_found

    return BusinessAccess(business=Business.from_snapshot(business_snapshot), member=member, user=user)
