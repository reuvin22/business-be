"""Business-to-business connections: relationships, customer prices, reviews, messages, verification."""

from google.cloud.firestore import Client, CollectionReference

from app.models.base import FirestoreModel
from app.models.business import business_subcollection
from app.schemas.enums import (
    ConversationStatus,
    RelationshipStatus,
    RelationshipType,
    ReviewStatus,
    VerificationStatus,
    VerificationType,
)
from app.schemas.network import CustomerPriceIn, OrderCard, Ratings

# ---- Relationships ---------------------------------------------------------------------
# Firestore location:  relationships/{relationshipId}


class Relationship(FirestoreModel):
    """Reads as: related_business is business's relationship_type. Example: Acme is Sunrise's SUPPLIER."""

    business_id: str  # the business that asked
    business_name: str
    related_business_id: str  # the business that was asked
    related_business_name: str
    business_ids: list[str]  # both ids, so each side can find it with one query
    relationship_type: RelationshipType
    status: RelationshipStatus = RelationshipStatus.PENDING
    requested_by_uid: str
    notes: str = ""
    started_at: int | None = None
    ended_at: int | None = None


def relationships_collection(db: Client) -> CollectionReference:
    return db.collection("relationships")


# ---- Customer-specific prices ----------------------------------------------------------
# Firestore location:  businesses/{sellerId}/customerPrices/{id}   (private to the seller and that customer)


class CustomerPrice(CustomerPriceIn, FirestoreModel):
    customer_business_name: str = ""


def customer_prices_collection(db: Client, business_id: str) -> CollectionReference:
    return business_subcollection(db, business_id, "customerPrices")


# ---- Reviews ---------------------------------------------------------------------------
# Firestore location:  businesses/{sellerId}/reviews/{orderId}
# The document id is the order id, so each order can be reviewed only once.


class Review(FirestoreModel):
    reviewer_business_id: str
    reviewer_business_name: str
    order_id: str
    ratings: Ratings
    rating: float  # average of the given ratings
    review: str = ""
    response: str = ""  # the seller's reply
    responded_at: int | None = None
    status: ReviewStatus = ReviewStatus.PUBLISHED


def reviews_collection(db: Client, business_id: str) -> CollectionReference:
    return business_subcollection(db, business_id, "reviews")


# ---- Conversations ---------------------------------------------------------------------
# Firestore locations:
#   conversations/{conversationId}
#   conversations/{conversationId}/messages/{messageId}


class Conversation(FirestoreModel):
    business_ids: list[str]  # the two businesses talking
    business_names: dict[str, str]  # {businessId: name}
    status: ConversationStatus = ConversationStatus.OPEN
    last_message: str = ""
    last_message_at: int = 0
    last_sender_business_id: str = ""
    last_read_at: dict[str, int] = {}  # {businessId: when that business last opened the chat}


class Message(FirestoreModel):
    sender_uid: str
    sender_name: str
    sender_business_id: str
    message: str
    attachments: list[str] = []
    order: OrderCard | None = None  # the order the message is about, as a small card
    edited_at: int | None = None  # set when the sender changed the text
    read_at: int | None = None


def conversations_collection(db: Client) -> CollectionReference:
    return db.collection("conversations")


def messages_collection(db: Client, conversation_id: str) -> CollectionReference:
    return conversations_collection(db).document(conversation_id).collection("messages")


# ---- Verification requests -------------------------------------------------------------
# Firestore location:  verificationRequests/{requestId}   (top-level so admins can list them all)


class VerificationRequest(FirestoreModel):
    business_id: str
    business_name: str
    verification_type: VerificationType
    document_ids: list[str] = []
    notes: str = ""
    status: VerificationStatus = VerificationStatus.PENDING
    submitted_at: int
    submitted_by: str  # user id
    reviewed_at: int | None = None
    reviewed_by: str | None = None  # admin's user id
    rejection_reason: str = ""


def verification_requests_collection(db: Client) -> CollectionReference:
    return db.collection("verificationRequests")
