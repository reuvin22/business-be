from pydantic import Field

from app.schemas.base import CamelModel
from app.schemas.enums import FulfillmentMethod, OrderStatus, PaymentStatus, PaymentTerm, PaymentType


class Address(CamelModel):
    recipient_name: str = ""
    phone: str = ""
    address_line_1: str = ""
    address_line_2: str = ""
    barangay: str = ""
    city: str = ""
    province: str = ""
    region: str = ""
    postal_code: str = ""
    country: str = "Philippines"


class OrderItemIn(CamelModel):
    product_id: str = Field(min_length=1)
    variant_id: str | None = None
    quantity: int = Field(ge=1)


class OrderIn(CamelModel):
    """A buyer's order to one seller (section 27). Prices are worked out by the server."""

    seller_business_id: str = Field(min_length=1)
    items: list[OrderItemIn] = Field(min_length=1)
    fulfillment_method: FulfillmentMethod = FulfillmentMethod.DELIVERY
    shipping_address: Address | None = None  # needed for DELIVERY and SHIPPING
    payment_method_type: PaymentType | None = None
    payment_term: PaymentTerm | None = None
    notes: str = ""


class QuoteLine(CamelModel):
    product_id: str
    variant_id: str | None
    product_name: str
    variant_name: str
    sku: str
    unit: str
    quantity: int
    unit_price: float | None  # None when no price applies
    subtotal: float


class Quote(CamelModel):
    """The price of an order before it is placed. `problems` lists anything that blocks the order."""

    lines: list[QuoteLine]
    subtotal: float
    delivery_fee: float
    total: float
    currency: str
    problems: list[str]


class OrderStatusIn(CamelModel):
    status: OrderStatus
    fulfillment_location_id: str | None = None  # the seller's location to take stock from (when confirming)
    reason: str = ""  # for cancelling or rejecting


class PaymentStatusIn(CamelModel):
    payment_status: PaymentStatus


class OrderChargesIn(CamelModel):
    """The seller can adjust the charges while the order is still PENDING."""

    delivery_fee: float = Field(ge=0)
    tax: float = Field(ge=0)
    discount: float = Field(ge=0)
