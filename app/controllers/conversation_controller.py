"""Messages between two businesses (section 26)."""

from google.cloud.firestore import Client, FieldFilter

from app.controllers import crud
from app.controllers.business_controller import find_business
from app.controllers.crud import bad_request, not_found
from app.core import cache
from app.dependencies.business_access import BusinessAccess
from app.models.network import Conversation, Message, conversations_collection, messages_collection
from app.schemas.enums import Permission
from app.schemas.network import MessageIn, StartConversationIn
from app.schemas.views import ConversationView, ConversationWithMessages
from app.utils.helpers import current_time_ms


def to_view(conversation: Conversation, my_business_id: str) -> ConversationView:
    other_id = next((b for b in conversation.business_ids if b != my_business_id), "")
    last_read = conversation.last_read_at.get(my_business_id, 0)
    unread = conversation.last_sender_business_id not in ("", my_business_id) and conversation.last_message_at > last_read
    return ConversationView(
        **conversation.model_dump(),
        other_business_id=other_id,
        other_business_name=conversation.business_names.get(other_id, ""),
        unread=unread,
    )


def list_conversations(db: Client, access: BusinessAccess) -> list[ConversationView]:
    def read() -> list[Conversation]:
        query = conversations_collection(db).where(filter=FieldFilter("businessIds", "array_contains", access.business_id))
        return [Conversation.from_snapshot(snapshot) for snapshot in query.stream()]

    conversations = cache.cached_models(cache.business_scope(access.business_id), "conversations", Conversation, read)
    conversations.sort(key=lambda c: c.last_message_at, reverse=True)
    return [to_view(c, access.business_id) for c in conversations]


def start_conversation(db: Client, access: BusinessAccess, start_in: StartConversationIn) -> ConversationView:
    """Opens (or re-uses) the conversation with another business and sends the first message."""
    access.require(Permission.SEND_MESSAGES)
    other_id = start_in.participant_business_id
    if other_id == access.business_id:
        raise bad_request("You cannot message your own business")
    other = find_business(db, other_id)
    if other is None:
        raise not_found("Business")

    existing = next((c for c in list_conversations(db, access) if c.other_business_id == other_id), None)
    if existing is None:
        now = current_time_ms()
        ref = conversations_collection(db).document()
        conversation = Conversation(
            id=ref.id,
            business_ids=[access.business_id, other_id],
            business_names={access.business_id: access.business.business_name, other_id: other.business_name},
            created_at=now,
            updated_at=now,
        )
        ref.set(conversation.to_firestore())
        conversation_id = ref.id
    else:
        conversation_id = existing.id

    send_message(db, access, conversation_id, MessageIn(message=start_in.message, attachments=start_in.attachments))
    return get_conversation(db, access, conversation_id)


def get_conversation(db: Client, access: BusinessAccess, conversation_id: str) -> ConversationView:
    conversation = crud.find_document(conversations_collection(db), conversation_id, Conversation)
    if conversation is None or access.business_id not in conversation.business_ids:
        raise not_found("Conversation")
    return to_view(conversation, access.business_id)


def open_conversation(db: Client, access: BusinessAccess, conversation_id: str) -> ConversationWithMessages:
    """Returns the messages and marks the other side's messages as read.

    The page asks for this every few seconds, so it only writes when something is actually unread.
    """
    conversation = get_conversation(db, access, conversation_id)
    messages = crud.list_documents(messages_collection(db, conversation_id), Message)

    unread = [m for m in messages if m.sender_business_id != access.business_id and m.read_at is None]
    if not unread and not conversation.unread:
        return ConversationWithMessages(conversation=conversation, messages=messages)

    now = current_time_ms()
    batch = db.batch()
    for message in unread:
        message.read_at = now
        batch.update(messages_collection(db, conversation_id).document(message.id), {"readAt": now})
    batch.update(conversations_collection(db).document(conversation_id), {f"lastReadAt.{access.business_id}": now})
    batch.commit()
    _clear_cache(conversation)

    conversation.last_read_at[access.business_id] = now
    conversation.unread = False
    return ConversationWithMessages(conversation=conversation, messages=messages)


def send_message(db: Client, access: BusinessAccess, conversation_id: str, message_in: MessageIn) -> Message:
    access.require(Permission.SEND_MESSAGES)
    get_conversation(db, access, conversation_id)

    now = current_time_ms()
    ref = messages_collection(db, conversation_id).document()
    message = Message(
        id=ref.id,
        sender_uid=access.user.uid,
        sender_name=access.user.name or access.user.email or "",
        sender_business_id=access.business_id,
        message=message_in.message,
        attachments=message_in.attachments,
        created_at=now,
        updated_at=now,
    )

    batch = db.batch()
    batch.set(ref, message.to_firestore())
    batch.update(
        conversations_collection(db).document(conversation_id),
        {
            "lastMessage": message.message[:200],
            "lastMessageAt": now,
            "lastSenderBusinessId": access.business_id,
            f"lastReadAt.{access.business_id}": now,
            "updatedAt": now,
        },
    )
    batch.commit()
    _clear_cache(get_conversation(db, access, conversation_id))
    return message


def _clear_cache(conversation: Conversation) -> None:
    """The conversation, its messages, and both businesses' conversation lists are now outdated."""
    cache.bump(
        cache.conversation_scope(conversation.id),
        *[cache.business_scope(business_id) for business_id in conversation.business_ids],
    )
