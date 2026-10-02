"""Schemas for business-to-business features: relationships, customer prices, reviews, messages
(sections 21-23, 26)."""

import datetime

from pydantic import Field, model_validator

from app.schemas.base import CamelModel, UrlText, check_date_order
from app.schemas.enums import RelationshipStatus, RelationshipType


class RelationshipIn(CamelModel):
    """Ask another business to connect. relationship_type = what THEY are to you."""

    related_business_id: str = Field(min_length=1)
    relationship_type: RelationshipType
    notes: str = ""


class RelationshipRespondIn(CamelModel):
    accept: bool


class RelationshipView(CamelModel):
    """A relationship as seen by one of the two businesses."""

    id: str
    other_business_id: str
    other_business_name: str
    their_role: RelationshipType  # what the other business is to you
    direction: str  # "OUTGOING" = you asked, "INCOMING" = they asked
    status: RelationshipStatus
    notes: str
    created_at: int
    started_at: int | None
    ended_at: int | None


class CustomerPriceIn(CamelModel):
    """A private price for one customer business, e.g. Retailer A pays 95 instead of 100."""

    customer_business_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    variant_id: str | None = None
    price: float = Field(ge=0)
    minimum_quantity: int = Field(default=1, ge=1)
    effective_from: datetime.date | None = None
    effective_until: datetime.date | None = None

    @model_validator(mode="after")
    def check_dates(self):
        check_date_order(self.effective_from, self.effective_until, "effective until must be after effective from")
        return self


class Ratings(CamelModel):
    """Separate 1-5 star scores. Leave a score empty if it does not apply."""

    product_quality: int | None = Field(default=None, ge=1, le=5)
    communication: int | None = Field(default=None, ge=1, le=5)
    delivery: int | None = Field(default=None, ge=1, le=5)
    packaging: int | None = Field(default=None, ge=1, le=5)
    accuracy: int | None = Field(default=None, ge=1, le=5)
    customer_service: int | None = Field(default=None, ge=1, le=5)

    def given_scores(self) -> list[int]:
        return [score for score in self.model_dump().values() if score is not None]


class ReviewIn(CamelModel):
    ratings: Ratings
    review: str = ""

    @model_validator(mode="after")
    def needs_a_score(self):
        if not self.ratings.given_scores():
            raise ValueError("give at least one rating")
        return self


class ReviewResponseIn(CamelModel):
    response: str = Field(min_length=1)


class StartConversationIn(CamelModel):
    participant_business_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    attachments: list[UrlText] = []
    order_id: str | None = None  # an order between the two businesses, shown as a card with the message


class MessageIn(CamelModel):
    message: str = Field(min_length=1)
    attachments: list[UrlText] = []
    order_id: str | None = None  # an order between the two businesses, shown as a card with the message


class OrderCardLine(CamelModel):
    product_name: str
    variant_name: str = ""
    quantity: int
    unit: str = ""
    unit_price: float | None = None  # None on cards sent before prices were included
    subtotal: float | None = None


class OrderCard(CamelModel):
    """The order a message is about, copied when it was sent (so the message never changes afterwards)."""

    order_id: str
    order_number: str
    items: list[OrderCardLine]
    total: float
    currency: str
    status: str
