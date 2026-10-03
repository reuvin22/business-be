"""Relationships, messages, and reviews about this business."""

from fastapi import APIRouter, Depends, status
from google.cloud.firestore import Client

from app.controllers import conversation_controller, relationship_controller, review_controller
from app.core.firebase import get_db
from app.dependencies.business_access import BusinessAccess, get_business_access
from app.models.network import Message, Review
from app.schemas.chat import MessageEditIn
from app.schemas.network import (
    MessageIn,
    RelationshipIn,
    RelationshipRespondIn,
    RelationshipView,
    ReviewResponseIn,
    StartConversationIn,
)
from app.schemas.views import ConversationView, ConversationWithMessages

router = APIRouter(prefix="/businesses/{business_id}", tags=["Network"])

# ---- Relationships --------------------------------------------------------------------------


@router.get("/relationships", response_model=list[RelationshipView])
def list_relationships(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return relationship_controller.list_relationships(db, access)


@router.post("/relationships", response_model=RelationshipView, status_code=status.HTTP_201_CREATED)
def request_relationship(
    relationship_in: RelationshipIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return relationship_controller.request_relationship(db, access, relationship_in)


@router.post("/relationships/{relationship_id}/respond", response_model=RelationshipView)
def respond_to_relationship(
    relationship_id: str,
    respond_in: RelationshipRespondIn,
    db: Client = Depends(get_db),
    access: BusinessAccess = Depends(get_business_access),
):
    return relationship_controller.respond_to_relationship(db, access, relationship_id, respond_in)


@router.post("/relationships/{relationship_id}/end", response_model=RelationshipView)
def end_relationship(relationship_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return relationship_controller.end_relationship(db, access, relationship_id)


# ---- Conversations ---------------------------------------------------------------------------


@router.get("/conversations", response_model=list[ConversationView])
def list_conversations(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return conversation_controller.list_conversations(db, access)


@router.post("/conversations", response_model=ConversationView, status_code=status.HTTP_201_CREATED)
def start_conversation(
    start_in: StartConversationIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return conversation_controller.start_conversation(db, access, start_in)


@router.get("/conversations/{conversation_id}", response_model=ConversationWithMessages)
def open_conversation(conversation_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return conversation_controller.open_conversation(db, access, conversation_id)


@router.post("/conversations/{conversation_id}/messages", response_model=Message, status_code=status.HTTP_201_CREATED)
def send_message(
    conversation_id: str, message_in: MessageIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return conversation_controller.send_message(db, access, conversation_id, message_in)


@router.put("/conversations/{conversation_id}/messages/{message_id}", response_model=Message)
def edit_message(
    conversation_id: str,
    message_id: str,
    edit_in: MessageEditIn,
    db: Client = Depends(get_db),
    access: BusinessAccess = Depends(get_business_access),
):
    """Only the sender may change their message."""
    return conversation_controller.edit_message(db, access, conversation_id, message_id, edit_in)


@router.delete("/conversations/{conversation_id}/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_message(
    conversation_id: str, message_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    """Only the sender may delete their message (for both businesses)."""
    conversation_controller.delete_message(db, access, conversation_id, message_id)


# ---- Reviews about this business ------------------------------------------------------------


@router.get("/reviews", response_model=list[Review])
def list_reviews(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return review_controller.list_reviews(db, access.business_id, include_hidden=True)


@router.post("/reviews/{review_id}/response", response_model=Review)
def respond_to_review(
    review_id: str, response_in: ReviewResponseIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return review_controller.respond_to_review(db, access, review_id, response_in)
