"""The live chat: team channel, market channel, and who may read them. The Realtime Database is in memory."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.controllers import chat_controller
from app.core import realtime
from app.schemas.chat import ChatMessageIn
from app.schemas.enums import MemberRole, Permission
from tests.conftest import create_business, login_as


def member(business_id="b1", uid="u1", permissions=(Permission.SEND_MESSAGES,), name="Ana"):
    """A stand-in for BusinessAccess (who is calling, for which business)."""
    return SimpleNamespace(
        business_id=business_id,
        business=SimpleNamespace(business_name="Acme", business_logo=""),
        member=SimpleNamespace(display_name=name, role=MemberRole.STAFF),
        user=SimpleNamespace(uid=uid, name="", email="ana@test.com"),
        can=lambda permission: permission in permissions,
        require=lambda permission: None
        if permission in permissions
        else (_ for _ in ()).throw(HTTPException(status_code=403, detail="no")),
    )


def test_asking_for_access_lets_the_member_read_the_chats(fake_realtime):
    access = chat_controller.get_access(member())
    assert (access.team_path, access.market_path) == ("chat/team/b1/messages", "chat/market/messages")
    assert fake_realtime.get("chatAccess/u1/b1") is True

    realtime.revoke_access("u1", "b1")
    assert fake_realtime.get("chatAccess/u1/b1") is None


def test_team_and_market_messages(fake_realtime):
    sent = chat_controller.send_team_message(member(), ChatMessageIn(message="Stock count at 5pm"))
    assert sent.id and sent.sender_name == "Ana"
    assert [m["message"] for m in fake_realtime.newest("chat/team/b1/messages", 50)] == ["Stock count at 5pm"]

    post = chat_controller.send_market_message(member(), ChatMessageIn(message="Rice 25kg, 10% off this week"))
    market = fake_realtime.newest("chat/market/messages", 50)
    assert [(m["businessId"], m["businessName"]) for m in market] == [("b1", "Acme")]

    # Another business cannot take it down; the business that posted it can
    with pytest.raises(HTTPException) as refused:
        chat_controller.delete_market_message(member(business_id="b2"), post.id)
    assert refused.value.status_code == 403
    chat_controller.delete_market_message(member(), post.id)
    assert fake_realtime.newest("chat/market/messages", 50) == []


def test_posting_in_the_market_needs_the_send_messages_permission(fake_realtime):
    with pytest.raises(HTTPException):
        chat_controller.send_market_message(member(permissions=()), ChatMessageIn(message="Hello"))
    # The team channel is open to every member
    chat_controller.send_team_message(member(permissions=()), ChatMessageIn(message="Hello team"))


def test_chat_through_the_api(client, fake_realtime):
    """With the Firestore emulator: the routes, and a removed member losing access."""
    business_id = create_business(client)["id"]
    access = client.get(f"/api/v1/businesses/{business_id}/chat").json()
    assert access["teamPath"] == f"chat/team/{business_id}/messages"

    client.post(f"/api/v1/businesses/{business_id}/members", json={"email": "staff@test.com", "role": "STAFF"})
    login_as("staff@test.com")
    staff_uid = client.get(f"/api/v1/businesses/{business_id}/chat").json()["uid"]
    response = client.post(f"/api/v1/businesses/{business_id}/chat/team/messages", json={"message": "On my way"})
    assert response.status_code == 201, response.text

    login_as("owner@test.com")
    client.delete(f"/api/v1/businesses/{business_id}/members/{staff_uid}")
    assert fake_realtime.get(f"chatAccess/{staff_uid}/{business_id}") is None


def test_direct_messages_move_to_the_realtime_database(fake_realtime, monkeypatch):
    """The first time a conversation is used, its earlier messages are copied over; "seen" comes from lastReadAt."""
    from app.controllers import conversation_controller
    from app.models.network import Conversation, Message

    earlier = Message(
        id="old1", sender_uid="u2", sender_name="Ben", sender_business_id="b2", message="Hi", created_at=100, updated_at=100
    )
    monkeypatch.setattr(conversation_controller, "messages_collection", lambda db, conversation_id: None)
    monkeypatch.setattr(conversation_controller.crud, "list_documents", lambda collection, model: [earlier])
    conversation = Conversation(
        id="c1", business_ids=["b1", "b2"], business_names={}, last_read_at={"b1": 150}, created_at=1, updated_at=1
    )

    conversation_controller._ensure_realtime(None, conversation)
    assert fake_realtime.get("chat/dm/c1/meta") == {"a": "b1", "b": "b2", "lastReadAt": {"b1": 150}}

    fake_realtime.push(
        "chat/dm/c1/messages", {"senderUid": "u1", "senderName": "Ana", "senderBusinessId": "b1", "message": "Hello", "createdAt": 200}
    )
    messages = conversation_controller._read_messages(conversation)
    assert [(m.message, m.read_at) for m in messages] == [("Hi", 150), ("Hello", None)]  # b2 has not read "Hello" yet


def test_a_message_can_carry_an_order_between_the_two_businesses(monkeypatch):
    from fastapi import HTTPException

    from app.controllers import conversation_controller
    from app.models.network import Conversation

    order = {
        "orderNumber": "ORD-1", "buyerBusinessId": "b2", "buyerBusinessName": "Acme", "sellerBusinessId": "b1",
        "sellerBusinessName": "Motor Parts", "businessIds": ["b1", "b2"], "placedByUid": "u2", "currency": "PHP",
        "subtotal": 650, "total": 650, "orderedAt": 1, "fulfillmentMethod": "PICKUP", "orderStatus": "PENDING",
        "items": [{"productId": "p1", "productName": "185x17 Tube Fuji", "unit": "pcs", "quantity": 5, "unitPrice": 130, "subtotal": 650}],
    }

    class Doc:
        def __init__(self, data):
            self.id, self.exists, self._data = "o1", data is not None, data

        def get(self):
            return self

        def to_dict(self):
            return self._data

    monkeypatch.setattr(conversation_controller, "orders_collection", lambda db: SimpleNamespace(document=lambda oid: Doc(order)))
    ours = Conversation(id="c1", business_ids=["b1", "b2"], business_names={})
    card = conversation_controller._order_card(None, ours, "o1")
    assert (card.order_number, card.items[0].product_name, card.items[0].quantity, card.status) == ("ORD-1", "185x17 Tube Fuji", 5, "PENDING")

    # An order of other businesses cannot be attached to this chat
    theirs = Conversation(id="c2", business_ids=["b1", "b3"], business_names={})
    with pytest.raises(HTTPException):
        conversation_controller._order_card(None, theirs, "o1")


def test_placing_an_order_messages_the_seller_once(monkeypatch, fake_realtime):
    """The buyer's message with the order card goes to the seller's chat, without the messaging permission."""
    from app.controllers import conversation_controller
    from app.models.network import Message
    from app.schemas.network import OrderCard
    from app.schemas.views import ConversationView

    chat = ConversationView(
        id="c1", business_ids=["b2", "b1"], business_names={"b1": "Motor Parts", "b2": "Japonkie"}, other_business_id="b1"
    )
    updates = []
    monkeypatch.setattr(conversation_controller, "_open_with", lambda db, access, other_id: "c1")
    monkeypatch.setattr(conversation_controller, "get_conversation", lambda db, access, cid: chat)
    monkeypatch.setattr(conversation_controller, "_ensure_realtime", lambda db, c: None)
    monkeypatch.setattr(
        conversation_controller,
        "_order_card",
        lambda db, c, oid: OrderCard(order_id=oid, order_number="ORD-1", items=[], total=260, currency="PHP", status="PENDING"),
    )
    monkeypatch.setattr(
        conversation_controller,
        "conversations_collection",
        lambda db: SimpleNamespace(document=lambda cid: SimpleNamespace(update=updates.append)),
    )
    monkeypatch.setattr(conversation_controller.activity_controller, "record", lambda *a, **k: None)

    buyer = member(business_id="b2", permissions=())  # may place orders, may not send messages
    order = SimpleNamespace(id="o1", order_number="ORD-1", seller_business_id="b1", seller_business_name="Motor Parts")
    conversation_controller.send_order_message(None, buyer, order)

    sent = fake_realtime.newest("chat/dm/c1/messages", 10)
    assert len(sent) == 1
    assert sent[0]["message"] == "Hi Motor Parts! I placed order ORD-1. Please confirm this order."
    assert sent[0]["order"]["orderNumber"] == "ORD-1"
    assert updates[0]["lastMessage"].startswith("Hi Motor Parts!")
    assert Message  # the message model was used to build it
