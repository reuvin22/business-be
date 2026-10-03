"""Messages between two businesses (section 26).

The list of conversations (who, last message, unread) is in Firestore. The messages themselves are in
the Realtime Database (chat/dm/{conversationId}, see app/core/realtime.py), so the page shows new ones
the moment they are sent. Messages from before that are copied there the first time a chat is opened."""

from google.cloud import firestore
from google.cloud.firestore import Client, FieldFilter

from app.controllers import activity_controller, crud
from app.controllers.business_controller import find_business
from app.controllers.chat_controller import run_message_change
from app.controllers.crud import bad_request, not_found
from app.core import cache, realtime
from app.dependencies.business_access import BusinessAccess
from app.models.network import Conversation, Message, conversations_collection, messages_collection
from app.models.trade import Order, orders_collection
from app.schemas.enums import ActivityCategory, Permission
from app.schemas.chat import MessageEditIn
from app.schemas.network import MessageIn, OrderCard, OrderCardLine, StartConversationIn
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
    conversation_id = _open_with(db, access, start_in.participant_business_id)
    _send(
        db,
        access,
        conversation_id,
        MessageIn(message=start_in.message, attachments=start_in.attachments, order_id=start_in.order_id),
    )
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

    return ConversationWithMessages(
        conversation=conversation,
        messages=_read_messages(conversation),
        realtime_key=realtime.room_key(realtime.dm_path(conversation_id)),  # one of the two businesses: may read it
    )


def _open_with(db: Client, access: BusinessAccess, other_id: str) -> str:
    """The id of the conversation with another business, made the first time."""
    if other_id == access.business_id:
        raise bad_request("You cannot message your own business")
    other = find_business(db, other_id)
    if other is None:
        raise not_found("Business")

    existing = next((c for c in list_conversations(db, access) if c.other_business_id == other_id), None)
    if existing is not None:
        return existing.id
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
    return ref.id


def send_message(db: Client, access: BusinessAccess, conversation_id: str, message_in: MessageIn) -> Message:
    access.require(Permission.SEND_MESSAGES)
    return _send(db, access, conversation_id, message_in)


def _send(db: Client, access: BusinessAccess, conversation_id: str, message_in: MessageIn) -> Message:
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
        order=_order_card(db, conversation, message_in.order_id) if message_in.order_id else None,
        created_at=now,
        updated_at=now,
    )

    # The message goes live first; then the conversation list is brought up to date
    store = realtime.get_store()
    messages_path = f"{realtime.dm_path(conversation_id)}/messages"
    message.id = store.push(messages_path, realtime.seal(messages_path, _to_realtime(message)))
    store.set(f"{realtime.dm_path(conversation_id)}/meta/lastReadAt/{access.business_id}", now)
    conversations_collection(db).document(conversation_id).update(
        Conversation.encrypt_fields(
            {
                "lastMessage": (message.message or "Sent a photo")[:200],
                "lastMessageAt": now,
                "lastSenderBusinessId": access.business_id,
                f"lastReadAt.{access.business_id}": now,
                "updatedAt": now,
            }
        )
    )
    _clear_cache(conversation)

    activity_controller.record(
        db,
        conversation.other_business_id,
        ActivityCategory.MESSAGES,
        "message.received",
        f"New message from {access.business.business_name}",
        by=access,
        detail=message.message or "Sent a photo",
        link=f"/messages?c={conversation_id}",
    )
    return message


def edit_message(db: Client, access: BusinessAccess, conversation_id: str, message_id: str, edit_in: MessageEditIn) -> Message:
    """The sender changes the text of their message (its photos and order card stay)."""
    conversation = get_conversation(db, access, conversation_id)
    path = f"{realtime.dm_path(conversation_id)}/messages/{message_id}"
    data = run_message_change(lambda: realtime.edit_message(path, access.user.uid, edit_in.message, current_time_ms()))
    _refresh_last_message(db, conversation)
    return _from_realtime(message_id, data)


def delete_message(db: Client, access: BusinessAccess, conversation_id: str, message_id: str) -> None:
    """The sender deletes their message, for both businesses."""
    conversation = get_conversation(db, access, conversation_id)
    run_message_change(lambda: realtime.delete_message(f"{realtime.dm_path(conversation_id)}/messages/{message_id}", access.user.uid))
    _refresh_last_message(db, conversation)


def _refresh_last_message(db: Client, conversation: Conversation) -> None:
    """The conversation list shows the newest message: after an edit or delete, it may be another one now."""
    newest = realtime.newest_messages(f"{realtime.dm_path(conversation.id)}/messages", 1)
    last = newest[0] if newest else {}
    last_message = (last.get("message") or ("Sent a photo" if last else ""))[:200]
    conversations_collection(db).document(conversation.id).update(
        Conversation.encrypt_fields({"lastMessage": last_message, "updatedAt": current_time_ms()})
    )
    _clear_cache(conversation)


def _from_realtime(message_id: str, item: dict) -> Message:
    created_at = item.get("createdAt", 0)
    return Message(
        id=message_id,
        sender_uid=item.get("senderUid", ""),
        sender_name=item.get("senderName", ""),
        sender_business_id=item.get("senderBusinessId", ""),
        message=item.get("message", ""),
        attachments=item.get("attachments") or [],
        order=item.get("order"),
        edited_at=item.get("editedAt"),
        created_at=created_at,
        updated_at=item.get("editedAt") or created_at,
    )


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
                **{f"messages/{m.id}": realtime.seal(path, _to_realtime(m)) for m in earlier},
            },
        )
    _realtime_ready.add(conversation.id)


def _to_realtime(message: Message) -> dict:
    data = {
        "senderUid": message.sender_uid,
        "senderName": message.sender_name,
        "senderBusinessId": message.sender_business_id,
        "message": message.message,
        "attachments": message.attachments,
        "createdAt": message.created_at,
    }
    if message.order:
        data["order"] = message.order.model_dump(mode="json", by_alias=True)
    return data


def _order_card(db: Client, conversation: Conversation, order_id: str) -> OrderCard:
    """The order as a card. It must be an order between the two businesses of the conversation."""
    snapshot = orders_collection(db).document(order_id).get()
    order = Order.from_snapshot(snapshot) if snapshot.exists else None
    if order is None or set(order.business_ids) != set(conversation.business_ids):
        raise not_found("Order")
    return OrderCard(
        order_id=order.id,
        order_number=order.order_number,
        items=[
            OrderCardLine(
                product_name=i.product_name,
                variant_name=i.variant_name,
                quantity=i.quantity,
                unit=i.unit,
                unit_price=i.unit_price,
                subtotal=i.subtotal,
            )
            for i in order.items
        ],
        total=order.total,
        currency=order.currency,
        status=order.order_status.value,
    )


def _read_messages(conversation: Conversation) -> list[Message]:
    """The newest messages, oldest first. A message is read once the other side opened the chat after it."""
    found = realtime.newest_messages(f"{realtime.dm_path(conversation.id)}/messages", realtime.MESSAGE_LIMIT)
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
                order=item.get("order"),
                edited_at=item.get("editedAt"),
                read_at=read_at if read_at >= created_at else None,
                created_at=created_at,
                updated_at=created_at,
            )
        )
    return messages
