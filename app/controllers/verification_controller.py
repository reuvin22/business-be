"""Business verification (section 20).

A business submits a request with documents. A platform admin reviews it and sets the result.
Only claim what was actually checked: see VerificationType in app/schemas/enums.py.
"""

from google.cloud.firestore import Client, FieldFilter

from app.controllers.crud import bad_request, not_found
from app.controllers.trust_controller import set_document_status
from app.dependencies.business_access import BusinessAccess
from app.models.business import Business, business_document, businesses_collection
from app.models.network import VerificationRequest, verification_requests_collection
from app.models.profile import documents_collection
from app.models.settings import settings_document
from app.schemas.enums import Permission, VerificationStatus, VerificationType
from app.schemas.trust import VerificationRequestIn, VerificationReviewIn
from app.schemas.user import CurrentUser
from app.utils.helpers import current_time_ms


def list_requests_for_business(db: Client, business_id: str) -> list[VerificationRequest]:
    query = verification_requests_collection(db).where(filter=FieldFilter("businessId", "==", business_id))
    requests = [VerificationRequest.from_snapshot(snapshot) for snapshot in query.stream()]
    return sorted(requests, key=lambda r: r.submitted_at, reverse=True)


def submit_request(db: Client, access: BusinessAccess, request_in: VerificationRequestIn) -> VerificationRequest:
    access.require(Permission.EDIT_BUSINESS)
    if any(r.status == VerificationStatus.PENDING for r in list_requests_for_business(db, access.business_id)):
        raise bad_request("You already have a request waiting for review")
    for document_id in request_in.document_ids:
        if not documents_collection(db, access.business_id).document(document_id).get().exists:
            raise bad_request("One of the attached documents no longer exists")

    now = current_time_ms()
    ref = verification_requests_collection(db).document()
    request = VerificationRequest(
        id=ref.id,
        business_id=access.business_id,
        business_name=access.business.business_name,
        verification_type=request_in.verification_type,
        document_ids=request_in.document_ids,
        notes=request_in.notes,
        submitted_at=now,
        submitted_by=access.user.uid,
        created_at=now,
        updated_at=now,
    )
    ref.set(request.to_firestore())

    # A business that is already verified keeps its badge while a higher level is reviewed
    if access.business.verification_status != VerificationStatus.VERIFIED:
        business_document(db, access.business_id).update({"verificationStatus": VerificationStatus.PENDING.value})
    return request


# ---- Platform admins ---------------------------------------------------------------------


def list_all_requests(db: Client, status: VerificationStatus | None = None) -> list[VerificationRequest]:
    collection = verification_requests_collection(db)
    query = collection.where(filter=FieldFilter("status", "==", status.value)) if status else collection
    requests = [VerificationRequest.from_snapshot(snapshot) for snapshot in query.stream()]
    return sorted(requests, key=lambda r: r.submitted_at, reverse=True)


def review_request(db: Client, admin: CurrentUser, request_id: str, review_in: VerificationReviewIn) -> VerificationRequest:
    snapshot = verification_requests_collection(db).document(request_id).get()
    if not snapshot.exists:
        raise not_found("Verification request")
    request = VerificationRequest.from_snapshot(snapshot)

    business_snapshot = business_document(db, request.business_id).get()
    if not business_snapshot.exists:
        raise not_found("Business")
    business = Business.from_snapshot(business_snapshot)

    now = current_time_ms()
    request.status = review_in.status
    request.rejection_reason = review_in.rejection_reason
    request.reviewed_at = now
    request.reviewed_by = admin.uid
    request.updated_at = now
    verification_requests_collection(db).document(request_id).set(request.to_firestore())

    # Update the business's badge
    if review_in.status == VerificationStatus.VERIFIED:
        business_changes = {"verificationStatus": "VERIFIED", "verificationLevel": request.verification_type.value}
    elif review_in.status == VerificationStatus.REJECTED and business.verification_status == VerificationStatus.VERIFIED:
        business_changes = {}  # a rejected upgrade keeps the existing badge
    else:
        business_changes = {"verificationStatus": review_in.status.value, "verificationLevel": None}
    if business_changes:
        business_document(db, request.business_id).update(business_changes)

    # Mark the attached documents with the same result
    if review_in.status in (VerificationStatus.VERIFIED, VerificationStatus.REJECTED):
        for document_id in request.document_ids:
            set_document_status(db, request.business_id, document_id, review_in.status)

    if request.verification_type == VerificationType.BUSINESS and review_in.status == VerificationStatus.VERIFIED:
        settings_document(db, request.business_id, "legal").set({"verificationStatus": "VERIFIED"}, merge=True)

    return request


def list_all_businesses(db: Client) -> list[Business]:
    businesses = [Business.from_snapshot(snapshot) for snapshot in businesses_collection(db).stream()]
    return sorted(businesses, key=lambda b: b.created_at, reverse=True)
