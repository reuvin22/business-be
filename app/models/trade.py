"""Buying and selling: orders (between businesses) and walk-in sales."""

from google.cloud.firestore import Client, CollectionReference

from app.models.base import FirestoreModel
from app.models.business import business_subcollection
from app.schemas.base import CamelModel
from app.schemas.enums import (
    DeliveryStatus,
    FulfillmentMethod,
    OrderStatus,
    PaymentStatus,
    PaymentTerm,
    PaymentType,
)
from app.schemas.order import Address
from app.schemas.sale import SaleIn

# ---- Orders ----------------------------------------------------------------------------
# Firestore location:  orders/{orderId}
# Orders are top-level because they belong to two businesses (buyer and seller).


class OrderItem(CamelModel):
    """One line of an order. Names and prices are copied so the order never changes afterwards."""

    product_id: str
    variant_id: str | None = None
    product_name: str
    variant_name: str = ""
    sku: str = ""
    unit: str = ""
    quantity: int
    unit_price: float
    discount: float = 0
    subtotal: float


class Order(FirestoreModel):
    order_number: str
    buyer_business_id: str
    buyer_business_name: str
    seller_business_id: str
    seller_business_name: str
    business_ids: list[str]  # [buyer, seller]; lets each side find its orders with one query
    placed_by_uid: str

    order_status: OrderStatus = OrderStatus.PENDING
    payment_status: PaymentStatus = PaymentStatus.UNPAID
    delivery_status: DeliveryStatus = DeliveryStatus.NOT_SHIPPED

    items: list[OrderItem]
    currency: str = "PHP"
    subtotal: float
    delivery_fee: float = 0
    tax: float = 0
    discount: float = 0
    total: float

    fulfillment_method: FulfillmentMethod
    shipping_address: Address | None = None
    payment_method_type: PaymentType | None = None
    payment_term: PaymentTerm | None = None
    notes: str = ""
    fulfillment_location_id: str | None = None  # seller's location the stock comes from
    status_reason: str = ""  # why it was cancelled or rejected
    reviewed: bool = False

    ordered_at: int
    confirmed_at: int | None = None
    shipped_at: int | None = None
    delivered_at: int | None = None
    completed_at: int | None = None
    cancelled_at: int | None = None


def orders_collection(db: Client) -> CollectionReference:
    return db.collection("orders")


# ---- Walk-in sales ---------------------------------------------------------------------
# Firestore location:  businesses/{businessId}/sales/{saleId}


class Sale(SaleIn, FirestoreModel):
    product_name: str = ""
    variant_name: str = ""
    unit_cost: float | None = None  # the product's cost price at the time of the sale
    # Set when the sale was made in the selling app (one receipt can have several sales)
    receipt_id: str = ""
    receipt_number: str = ""


def sales_collection(db: Client, business_id: str) -> CollectionReference:
    return business_subcollection(db, business_id, "sales")
