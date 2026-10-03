"""The live chat channels (section 26): the team channel inside a business, and the public market
channel where every business can post offers and announcements. Messages live in the Realtime Database
(see app/core/realtime.py); the browser listens to them and sends through the API."""

from app.controllers.crud import bad_request, forbidden, not_found
from app.core import realtime
from app.dependencies.business_access import BusinessAccess
from app.schemas.chat import ChatAccess, ChatMessage, ChatMessageIn, MessageEditIn
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
        # The keys to decrypt them with (this member may read all three)
        team_key=realtime.room_key(realtime.team_path(access.business_id)),
        market_key=realtime.room_key(realtime.MARKET_PATH),
        live_key=realtime.room_key(realtime.live_path(access.business_id)),
    )


def send_team_message(access: BusinessAccess, message_in: ChatMessageIn) -> ChatMessage:
    """Every member of the team may write in its channel."""
    return _post(access, realtime.team_path(access.business_id), message_in)


def send_market_message(access: BusinessAccess, message_in: ChatMessageIn) -> ChatMessage:
    """Posts in the public market channel, in the name of the business."""
    access.require(Permission.SEND_MESSAGES)
    return _post(access, realtime.MARKET_PATH, message_in)


def delete_market_message(access: BusinessAccess, message_id: str) -> None:
    """The sender takes back their post; so may their business (any member who may send messages)."""
    by_business = access.business_id if access.can(Permission.SEND_MESSAGES) else ""
    run_message_change(lambda: realtime.delete_message(f"{realtime.MARKET_PATH}/{message_id}", access.user.uid, by_business=by_business))


def edit_market_message(access: BusinessAccess, message_id: str, edit_in: MessageEditIn) -> ChatMessage:
    path = f"{realtime.MARKET_PATH}/{message_id}"
    return _as_message(message_id, run_message_change(lambda: realtime.edit_message(path, access.user.uid, edit_in.message, current_time_ms())))


def edit_team_message(access: BusinessAccess, message_id: str, edit_in: MessageEditIn) -> ChatMessage:
    path = f"{realtime.team_path(access.business_id)}/{message_id}"
    return _as_message(message_id, run_message_change(lambda: realtime.edit_message(path, access.user.uid, edit_in.message, current_time_ms())))


def delete_team_message(access: BusinessAccess, message_id: str) -> None:
    run_message_change(lambda: realtime.delete_message(f"{realtime.team_path(access.business_id)}/{message_id}", access.user.uid))


def run_message_change(action):
    """Runs an edit or delete of a message, turning its errors into answers for the browser."""
    try:
        return action()
    except LookupError:
        raise not_found("Message") from None
    except PermissionError as error:
        raise forbidden(str(error)) from None
    except ValueError as error:
        raise bad_request(str(error)) from None


def _as_message(message_id: str, data: dict) -> ChatMessage:
    return ChatMessage.model_validate({**data, "id": message_id})


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
    message.id = realtime.get_store().push(path, realtime.seal(path, data))
    return message
