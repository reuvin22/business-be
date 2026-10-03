"""Business details that exist once per business (not lists).

Firestore location:  businesses/{businessId}/settings/{name}
where name is "legal", "delivery", "paymentTerms", "returnPolicy", "supplierProfile", or "pos".
"""

from google.cloud.firestore import Client, DocumentReference

from app.models.base import FirestoreModel
from app.models.business import business_subcollection
from app.schemas.delivery import DeliverySettingsIn
from app.schemas.enums import VerificationStatus
from app.schemas.legal import LegalIn
from app.schemas.payment import PaymentTermsIn
from app.schemas.policies import ReturnPolicyIn, SupplierProfileIn
from app.schemas.pos import PosSettingsIn


class PosSettings(PosSettingsIn, FirestoreModel):
    pass


class LegalInfo(LegalIn, FirestoreModel):
    # Encrypted in Firestore: registration, tax, permit, and license details (see app/core/crypto.py)
    encrypted_fields = (
        "registration_number",
        "registration_date",
        "tax_identification_number",
        "business_permit_number",
        "business_permit_expiry",
        "license_number",
        "license_expiry",
        "legal_document_urls",
    )

    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED  # set by platform admins


class DeliverySettings(DeliverySettingsIn, FirestoreModel):
    pass


class PaymentTerms(PaymentTermsIn, FirestoreModel):
    # Encrypted in Firestore: credit given to customers (see app/core/crypto.py)
    encrypted_fields = ("credit_limit", "credit_days", "down_payment_percentage", "notes")


class ReturnPolicy(ReturnPolicyIn, FirestoreModel):
    pass


class SupplierProfile(SupplierProfileIn, FirestoreModel):
    pass


def settings_document(db: Client, business_id: str, name: str) -> DocumentReference:
    return business_subcollection(db, business_id, "settings").document(name)
