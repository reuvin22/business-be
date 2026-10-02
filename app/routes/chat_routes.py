"""The live chat channels: the team channel and the public market channel (direct messages are in network_routes)."""

from fastapi import APIRouter, Depends, status

from app.controllers import chat_controller
from app.dependencies.business_access import BusinessAccess, get_business_access
from app.schemas.chat import ChatAccess, ChatMessage, ChatMessageIn

router = APIRouter(prefix="/businesses/{business_id}/chat", tags=["Chat"])


@router.get("", response_model=ChatAccess)
def get_chat_access(access: BusinessAccess = Depends(get_business_access)):
    """Call this before listening to the chats in the Realtime Database: it lets you read them."""
    return chat_controller.get_access(access)


@router.post("/team/messages", response_model=ChatMessage, status_code=status.HTTP_201_CREATED)
def send_team_message(message_in: ChatMessageIn, access: BusinessAccess = Depends(get_business_access)):
    return chat_controller.send_team_message(access, message_in)


@router.post("/market/messages", response_model=ChatMessage, status_code=status.HTTP_201_CREATED)
def send_market_message(message_in: ChatMessageIn, access: BusinessAccess = Depends(get_business_access)):
    """Posts in the public market channel, which every business on the platform can read."""
    return chat_controller.send_market_message(access, message_in)


@router.delete("/market/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_market_message(message_id: str, access: BusinessAccess = Depends(get_business_access)):
    chat_controller.delete_market_message(access, message_id)
