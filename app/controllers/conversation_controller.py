"""Messages between two businesses (section 26).

The list of conversations (who, last message, unread) is in Firestore. The messages themselves are in
the Realtime Database (chat/dm/{conversationId}, see app/core/realtime.py), so the page shows new ones
the moment they are sent. Messages from before that are copied there the first time a chat is opened."""

from google.cloud import firestore
from google.cloud.firestore import Client, FieldFilter

from app.controllers import activity_controller, crud
from app.controllers.business_controller import find_business
from app.controllers.crud import bad_request, not_found
from app.core import cache, realtime
from app.dependencies.business_access import BusinessAccess
from app.models.network import Conversation, Message, conversations_collection, messages_collection
from app.schemas.enums import ActivityCategory, Permission
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
        latest_first = query.order_by("lastMessageAt", direction=firestore.Query.DESCENDING)
        return [Conversation.from_snapshot(snapshot) for snapshot in crud.stream_indexed(latest_first, fallback=query)]

    conversations = cache.cached_models(cache.chat_scope(access.business_id), "conversations", Conversation, read)
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
        _ensure_realtime(db, conversation)
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
    """Returns the newest messages and marks the conversation as read by this business.

    The page calls this when a chat opens and when a new message arrives in it, so it only writes
    when something is actually unread."""
    conversation = get_conversation(db, access, conversation_id)
    _ensure_realtime(db, conversation)

    if conversation.unread:
        now = current_time_ms()
        conversations_collection(db).document(conversation_id).update({f"lastReadAt.{access.business_id}": now})
        realtime.get_store().set(f"{realtime.dm_path(conversation_id)}/meta/lastReadAt/{access.business_id}", now)
        _clear_cache(conversation)
        conversation.last_read_at[access.business_id] = now
        conversation.unread = False

    return ConversationWithMessages(conversation=conversation, messages=_read_messages(conversation))


def send_message(db: Client, access: BusinessAccess, conversation_id: str, message_in: MessageIn) -> Message:
    access.require(Permission.SEND_MESSAGES)
    conversation = get_conversation(db, access, conversation_id)
    _ensure_realtime(db, conversation)

    now = current_time_ms()
    message = Message(
        id="",
        sender_uid=access.user.uid,
        sender_name=access.member.display_name or access.user.name or access.user.email or "",
        sender_business_id=access.business_id,
        message=message_in.message,
        attachments=message_in.attachments,
        created_at=now,
        updated_at=now,
    )

    # The message goes live first; then the conversation list is brought up to date
    store = realtime.get_store()
    message.id = store.push(f"{realtime.dm_path(conversation_id)}/messages", _to_realtime(message))
    store.set(f"{realtime.dm_path(conversation_id)}/meta/lastReadAt/{access.business_id}", now)
    conversations_collection(db).document(conversation_id).update(
        {
            "lastMessage": message.message[:200],
            "lastMessageAt": now,
            "lastSenderBusinessId": access.business_id,
            f"lastReadAt.{access.business_id}": now,
            "updatedAt": now,
        }
    )
    _clear_cache(conversation)

    activity_controller.record(
        db,
        conversation.other_business_id,
        ActivityCategory.MESSAGES,
        "message.received",
        f"New message from {access.business.business_name}",
        by=access,
        detail=message.message,
        link=f"/messages?c={conversation_id}",
    )
    return message


def _clear_cache(conversation: Conversation) -> None:
    """The conversation and both businesses' conversation lists are now outdated.
    Only their chat part: products, prices, and the rest stay cached."""
    cache.bump(
        cache.conversation_scope(conversation.id),
        *[cache.chat_scope(business_id) for business_id in conversation.business_ids],
    )


# ---- The messages in the Realtime Database ------------------------------------------------------

# Conversations this server already set up in the Realtime Database (saves a read on every message)
_realtime_ready: set[str] = set()


def _ensure_realtime(db: Client, conversation: Conversation) -> None:
    """Makes sure the conversation exists in the Realtime Database: who is in it (the rules use this to
    decide who may read it), when each side last read it, and the messages sent before it moved there."""
    if conversation.id in _realtime_ready:
        return
    store = realtime.get_store()
    path = realtime.dm_path(conversation.id)
    if store.get(f"{path}/meta") is None:
        first, second = conversation.business_ids
        earlier = crud.list_documents(messages_collection(db, conversation.id), Message)
        read_times = {business_id: at for business_id, at in conversation.last_read_at.items() if at}
        store.update(
            path,
            {
                "meta": {"a": first, "b": second, "lastReadAt": read_times},
                **{f"messages/{m.id}": _to_realtime(m) for m in earlier},
            },
        )
    _realtime_ready.add(conversation.id)


def _to_realtime(message: Message) -> dict:
    return {
        "senderUid": message.sender_uid,
        "senderName": message.sender_name,
        "senderBusinessId": message.sender_business_id,
        "message": message.message,
        "attachments": message.attachments,
        "createdAt": message.created_at,
    }


def _read_messages(conversation: Conversation) -> list[Message]:
    """The newest messages, oldest first. A message is read once the other side opened the chat after it."""
    found = realtime.get_store().newest(f"{realtime.dm_path(conversation.id)}/messages", realtime.MESSAGE_LIMIT)
    messages = []
    for item in found:
        created_at = item.get("createdAt", 0)
        others = [b for b in conversation.business_ids if b != item.get("senderBusinessId")]
        read_at = max((conversation.last_read_at.get(b, 0) for b in others), default=0)
        messages.append(
            Message(
                id=item["id"],
                sender_uid=item.get("senderUid", ""),
                sender_name=item.get("senderName", ""),
                sender_business_id=item.get("senderBusinessId", ""),
                message=item.get("message", ""),
                attachments=item.get("attachments") or [],
                read_at=read_at if read_at >= created_at else None,
                created_at=created_at,
                updated_at=created_at,
            )
        )
    return messages
