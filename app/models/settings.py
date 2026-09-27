"""Business details that exist once per business (not lists).

Firestore location:  businesses/{businessId}/settings/{name}
where name is "legal", "delivery", "paymentTerms", "returnPolicy", or "supplierProfile".
"""

from google.cloud.firestore import Client, DocumentReference

from app.models.base import FirestoreModel
from app.models.business import business_subcollection
from app.schemas.delivery import DeliverySettingsIn
from app.schemas.enums import VerificationStatus
from app.schemas.legal import LegalIn
from app.schemas.payment import PaymentTermsIn
from app.schemas.policies import ReturnPolicyIn, SupplierProfileIn


class LegalInfo(LegalIn, FirestoreModel):
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED  # set by platform admins


class DeliverySettings(DeliverySettingsIn, FirestoreModel):
    pass


class PaymentTerms(PaymentTermsIn, FirestoreModel):
    pass


class ReturnPolicy(ReturnPolicyIn, FirestoreModel):
    pass


class SupplierProfile(SupplierProfileIn, FirestoreModel):
    pass


def settings_document(db: Client, business_id: str, name: str) -> DocumentReference:
    return business_subcollection(db, business_id, "settings").document(name)
