"""The live chat channels (section 26): the team channel inside a business, and the public market
channel where every business can post offers and announcements. Messages live in the Realtime Database
(see app/core/realtime.py); the browser listens to them and sends through the API."""

from app.controllers.crud import forbidden, not_found
from app.core import realtime
from app.dependencies.business_access import BusinessAccess
from app.schemas.chat import ChatAccess, ChatMessage, ChatMessageIn
from app.schemas.enums import Permission
from app.utils.helpers import current_time_ms


def get_access(access: BusinessAccess) -> ChatAccess:
    """Lets this member read the business's chats live, and says where they are.

    Only active members (not seller accounts) get here, so this is where reading is granted.
    Removing a member, or making them inactive, takes it away again (see member_controller)."""
    realtime.grant_access(access.user.uid, access.business_id)
    return ChatAccess(
        uid=access.user.uid,
        business_id=access.business_id,
        team_path=realtime.team_path(access.business_id),
        market_path=realtime.MARKET_PATH,
    )


def send_team_message(access: BusinessAccess, message_in: ChatMessageIn) -> ChatMessage:
    """Every member of the team may write in its channel."""
    return _post(access, realtime.team_path(access.business_id), message_in)


def send_market_message(access: BusinessAccess, message_in: ChatMessageIn) -> ChatMessage:
    """Posts in the public market channel, in the name of the business."""
    access.require(Permission.SEND_MESSAGES)
    return _post(access, realtime.MARKET_PATH, message_in)


def delete_market_message(access: BusinessAccess, message_id: str) -> None:
    """A business may take back its own market posts."""
    access.require(Permission.SEND_MESSAGES)
    store = realtime.get_store()
    path = f"{realtime.MARKET_PATH}/{message_id}"
    message = store.get(path)
    if not message:
        raise not_found("Message")
    if message.get("businessId") != access.business_id:
        raise forbidden("You can only delete your own business's posts")
    store.delete(path)


def _post(access: BusinessAccess, path: str, message_in: ChatMessageIn) -> ChatMessage:
    message = ChatMessage(
        sender_uid=access.user.uid,
        sender_name=access.member.display_name or access.user.name or access.user.email or "",
        business_id=access.business_id,
        business_name=access.business.business_name,
        business_logo=access.business.business_logo,
        message=message_in.message.strip(),
        attachments=message_in.attachments,
        created_at=current_time_ms(),
    )
    data = message.model_dump(mode="json", by_alias=True, exclude={"id"})
    message.id = realtime.get_store().push(path, data)
    return message
