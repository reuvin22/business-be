"""The public side of the platform: find businesses and see their profiles and catalogs.
Any logged-in user can use these."""

from fastapi import APIRouter, Depends
from google.cloud.firestore import Client

from app.controllers import category_controller, directory_controller
from app.core.firebase import get_db
from app.dependencies.auth import get_current_user
from app.models.category import Category
from app.models.network import Review
from app.schemas.business import BusinessSummary
from app.schemas.directory import PublicProduct, PublicProfile
from app.schemas.enums import BusinessType
from app.schemas.user import CurrentUser

router = APIRouter(tags=["Directory"])


@router.get("/me", response_model=CurrentUser)
def get_me(user: CurrentUser = Depends(get_current_user)):
    """The logged-in user (and whether they are a platform admin)."""
    return user


@router.get("/categories", response_model=list[Category])
def list_categories(db: Client = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    return category_controller.list_categories(db)


@router.get("/directory/businesses", response_model=list[BusinessSummary])
def search_businesses(
    q: str = "",
    type: BusinessType | None = None,
    capability: str = "",
    category_id: str = "",
    city: str = "",
    verified_only: bool = False,
    db: Client = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Example: /api/directory/businesses?type=SUPPLIER&capability=privateLabel"""
    return directory_controller.search_businesses(db, q, type, capability, category_id, city, verified_only)


@router.get("/directory/businesses/{business_id}", response_model=PublicProfile)
def get_public_profile(business_id: str, db: Client = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    return directory_controller.get_public_profile(db, business_id)


@router.get("/directory/businesses/{business_id}/products", response_model=list[PublicProduct])
def list_public_products(
    business_id: str,
    buyer_business_id: str | None = None,
    db: Client = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return directory_controller.list_public_products(db, user, business_id, buyer_business_id)


@router.get("/directory/businesses/{business_id}/reviews", response_model=list[Review])
def list_public_reviews(business_id: str, db: Client = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    return directory_controller.list_public_reviews(db, business_id)
