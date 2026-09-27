"""Platform admin tools: verification reviews, categories, and moderation.
Admins are the emails listed in ADMIN_EMAILS (.env)."""

from fastapi import APIRouter, Depends, status
from google.cloud.firestore import Client

from app.controllers import category_controller, review_controller, trust_controller, verification_controller
from app.core.firebase import get_db
from app.dependencies.auth import require_admin
from app.models.business import Business
from app.models.category import Category
from app.models.network import Review, VerificationRequest
from app.models.profile import BusinessDocument, Certification
from app.schemas.category import CategoryIn
from app.schemas.enums import ReviewStatus, VerificationStatus
from app.schemas.trust import StatusIn, VerificationReviewIn
from app.schemas.user import CurrentUser

router = APIRouter(prefix="/admin", tags=["Platform admin"])

# ---- Verification -----------------------------------------------------------------------------


@router.get("/verifications", response_model=list[VerificationRequest])
def list_verification_requests(
    status: VerificationStatus | None = None, db: Client = Depends(get_db), admin: CurrentUser = Depends(require_admin)
):
    return verification_controller.list_all_requests(db, status)


@router.post("/verifications/{request_id}/review", response_model=VerificationRequest)
def review_verification_request(
    request_id: str,
    review_in: VerificationReviewIn,
    db: Client = Depends(get_db),
    admin: CurrentUser = Depends(require_admin),
):
    return verification_controller.review_request(db, admin, request_id, review_in)


@router.get("/businesses", response_model=list[Business])
def list_all_businesses(db: Client = Depends(get_db), admin: CurrentUser = Depends(require_admin)):
    return verification_controller.list_all_businesses(db)


@router.get("/businesses/{business_id}/documents", response_model=list[BusinessDocument])
def list_business_documents(business_id: str, db: Client = Depends(get_db), admin: CurrentUser = Depends(require_admin)):
    return trust_controller.list_documents(db, business_id)


@router.get("/businesses/{business_id}/certifications", response_model=list[Certification])
def list_business_certifications(
    business_id: str, db: Client = Depends(get_db), admin: CurrentUser = Depends(require_admin)
):
    return trust_controller.list_certifications(db, business_id)


@router.post("/businesses/{business_id}/certifications/{cert_id}/status", response_model=Certification)
def set_certification_status(
    business_id: str, cert_id: str, status_in: StatusIn, db: Client = Depends(get_db), admin: CurrentUser = Depends(require_admin)
):
    return trust_controller.set_certification_status(db, business_id, cert_id, status_in.status)


@router.post("/businesses/{business_id}/reviews/{review_id}/hide", response_model=Review)
def hide_review(business_id: str, review_id: str, db: Client = Depends(get_db), admin: CurrentUser = Depends(require_admin)):
    return review_controller.set_review_status(db, business_id, review_id, ReviewStatus.HIDDEN)


# ---- Categories -------------------------------------------------------------------------------


@router.post("/categories", response_model=Category, status_code=status.HTTP_201_CREATED)
def create_category(category_in: CategoryIn, db: Client = Depends(get_db), admin: CurrentUser = Depends(require_admin)):
    return category_controller.create_category(db, category_in)


@router.put("/categories/{category_id}", response_model=Category)
def update_category(
    category_id: str, category_in: CategoryIn, db: Client = Depends(get_db), admin: CurrentUser = Depends(require_admin)
):
    return category_controller.update_category(db, category_id, category_in)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(category_id: str, db: Client = Depends(get_db), admin: CurrentUser = Depends(require_admin)):
    category_controller.delete_category(db, category_id)


@router.post("/categories/defaults", response_model=list[Category])
def load_default_categories(db: Client = Depends(get_db), admin: CurrentUser = Depends(require_admin)):
    """Adds a starter category tree (only when there are no categories yet)."""
    return category_controller.load_default_categories(db)
