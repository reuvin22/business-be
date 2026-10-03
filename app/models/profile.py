"""Lists that describe a business: contacts, locations, brands, delivery zones, payment methods,
certifications, social links, and documents.

Firestore location:  businesses/{businessId}/{collection}/{id}
"""

from google.cloud.firestore import Client, CollectionReference

from app.models.base import FirestoreModel
from app.models.business import business_subcollection
from app.schemas.brand import BrandIn
from app.schemas.contact import ContactIn
from app.schemas.delivery import DeliveryZoneIn
from app.schemas.enums import VerificationStatus
from app.schemas.location import LocationIn
from app.schemas.payment import PaymentMethodIn
from app.schemas.trust import CertificationIn, DocumentIn, SocialLinkIn


class Contact(ContactIn, FirestoreModel):
    # Encrypted in Firestore: personal contact details (see app/core/crypto.py)
    encrypted_fields = ("email", "phone")

    is_verified: bool = False  # True when the contact is linked to an active team member


class Location(LocationIn, FirestoreModel):
    pass


class Brand(BrandIn, FirestoreModel):
    pass


class DeliveryZone(DeliveryZoneIn, FirestoreModel):
    pass


class PaymentMethod(PaymentMethodIn, FirestoreModel):
    # Encrypted in Firestore: where buyers send money (see app/core/crypto.py)
    encrypted_fields = ("account_name", "account_number", "instructions")


class Certification(CertificationIn, FirestoreModel):
    # Encrypted in Firestore: the certificate itself (see app/core/crypto.py)
    encrypted_fields = ("certificate_number", "document_url")

    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED  # set by platform admins


class SocialLink(SocialLinkIn, FirestoreModel):
    verified: bool = False


class BusinessDocument(DocumentIn, FirestoreModel):
    # Encrypted in Firestore: permits, IDs, contracts (see app/core/crypto.py)
    encrypted_fields = ("file_url", "file_name", "issue_date", "expiry_date")

    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED  # set by platform admins
    verified_at: int | None = None
    # "uploaded at" is created_at


def contacts_collection(db: Client, business_id: str) -> CollectionReference:
    return business_subcollection(db, business_id, "contacts")


def locations_collection(db: Client, business_id: str) -> CollectionReference:
    return business_subcollection(db, business_id, "locations")


def brands_collection(db: Client, business_id: str) -> CollectionReference:
    return business_subcollection(db, business_id, "brands")


def delivery_zones_collection(db: Client, business_id: str) -> CollectionReference:
    return business_subcollection(db, business_id, "deliveryZones")


def payment_methods_collection(db: Client, business_id: str) -> CollectionReference:
    return business_subcollection(db, business_id, "paymentMethods")


def certifications_collection(db: Client, business_id: str) -> CollectionReference:
    return business_subcollection(db, business_id, "certifications")


def social_links_collection(db: Client, business_id: str) -> CollectionReference:
    return business_subcollection(db, business_id, "socialLinks")


def documents_collection(db: Client, business_id: str) -> CollectionReference:
    return business_subcollection(db, business_id, "documents")
