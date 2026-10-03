from google.cloud.firestore import Client, CollectionReference, DocumentReference

from app.models.base import FirestoreModel
from app.schemas.business import BusinessIn
from app.schemas.enums import VerificationStatus, VerificationType

# Firestore location:  businesses/{businessId}
#
# Everything that belongs to one business is stored in sub-collections under it:
#   businesses/{businessId}/members, /contacts, /locations, /products, /inventory, ...


class Business(BusinessIn, FirestoreModel):
    # Encrypted in Firestore: contact details (see app/core/crypto.py)
    encrypted_fields = ("primary_email", "primary_phone")

    # ---- Set by the system, not by the form ----
    owner_uid: str = ""
    # User ids of the ACTIVE members. Lets us find "my businesses" with one query.
    member_uids: list[str] = []
    # User ids of the ACTIVE seller accounts (selling app only). Kept apart from member_uids, so the
    # business does not show up in a seller's "my businesses" list in the main app.
    seller_uids: list[str] = []
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    verification_level: VerificationType | None = None
    # Copied from other documents so the directory can filter without extra reads:
    capabilities: list[str] = []  # from the supplier profile, e.g. ["privateLabel"]
    primary_city: str = ""  # from the primary location
    primary_province: str = ""
    rating_average: float = 0
    rating_count: int = 0
    # Goes up when someone leaves the team, so the chats get new keys (see app/core/realtime.py)
    chat_key_version: int = 0


    def file_urls(self) -> list[str]:
        return [self.business_logo, self.cover_image]


def businesses_collection(db: Client) -> CollectionReference:
    return db.collection("businesses")


def business_document(db: Client, business_id: str) -> DocumentReference:
    return businesses_collection(db).document(business_id)


def business_subcollection(db: Client, business_id: str, name: str) -> CollectionReference:
    """A collection inside one business, e.g. business_subcollection(db, id, "contacts")."""
    return business_document(db, business_id).collection(name)
