"""Response shapes that add extra, calculated information to a stored model."""

from app.models.network import Conversation, Message
from app.models.trade import Order
from app.schemas.base import CamelModel
from app.schemas.payment import PaymentInstructions


class OrderView(Order):
    """An order, plus how to pay it (only shown to the buyer after the seller confirms)."""

    payment_instructions: list[PaymentInstructions] = []


class ConversationView(Conversation):
    """A conversation as one business sees it."""

    other_business_id: str = ""
    other_business_name: str = ""
    unread: bool = False


class ConversationWithMessages(CamelModel):
    conversation: ConversationView
    messages: list[Message]
