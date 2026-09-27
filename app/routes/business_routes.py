from fastapi import APIRouter, Depends, status
from google.cloud.firestore import Client

from app.controllers import business_controller, member_controller
from app.core.firebase import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.business_access import BusinessAccess, get_business_access
from app.models.business import Business
from app.models.member import Member
from app.schemas.business import BusinessIn, MyRole
from app.schemas.member import MemberAddIn, MemberUpdateIn
from app.schemas.user import CurrentUser
from app.schemas.views import BusinessContext

router = APIRouter(prefix="/businesses", tags=["Businesses & team"])


# ---- Businesses ---------------------------------------------------------------------------


@router.get("", response_model=list[Business])
def list_my_businesses(db: Client = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    return business_controller.list_my_businesses(db, user)


@router.post("", response_model=Business, status_code=status.HTTP_201_CREATED)
def create_business(
    business_in: BusinessIn, db: Client = Depends(get_db), user: CurrentUser = Depends(get_current_user)
):
    return business_controller.create_business(db, user, business_in)


@router.get("/{business_id}", response_model=Business)
def get_business(access: BusinessAccess = Depends(get_business_access)):
    return access.business


@router.get("/{business_id}/context", response_model=BusinessContext)
def get_business_context(access: BusinessAccess = Depends(get_business_access)):
    """The business and your role in it, in one request. The business pages load this first."""
    return business_controller.get_context(access)


@router.get("/{business_id}/my-role", response_model=MyRole)
def get_my_role(access: BusinessAccess = Depends(get_business_access)):
    return business_controller.get_my_role(access)


@router.put("/{business_id}", response_model=Business)
def update_business(
    business_in: BusinessIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return business_controller.update_business(db, access, business_in)


@router.delete("/{business_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_business(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    business_controller.delete_business(db, access)


# ---- Team members -------------------------------------------------------------------------


@router.get("/{business_id}/members", response_model=list[Member])
def list_members(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return member_controller.list_members(db, access)


@router.post("/{business_id}/members", response_model=Member, status_code=status.HTTP_201_CREATED)
def add_member(
    member_in: MemberAddIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return member_controller.add_member(db, access, member_in)


@router.put("/{business_id}/members/{user_id}", response_model=Member)
def update_member(
    user_id: str,
    member_in: MemberUpdateIn,
    db: Client = Depends(get_db),
    access: BusinessAccess = Depends(get_business_access),
):
    return member_controller.update_member(db, access, user_id, member_in)


@router.delete("/{business_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(user_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    member_controller.remove_member(db, access, user_id)
