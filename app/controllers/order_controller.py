"""Orders between businesses (section 27).

Life of an order:
    PENDING --seller--> CONFIRMED --seller--> SHIPPED --seller--> DELIVERED --buyer--> COMPLETED
       |                    |
       |--seller--> REJECTED   --seller--> CANCELLED
       |--buyer---> CANCELLED

Stock: confirming reserves it at the chosen location, shipping takes it out,
cancelling a confirmed order releases the reservation.
"""

import datetime
from collections import defaultdict

from google.cloud import firestore
from google.cloud.firestore import Client, DocumentReference, FieldFilter, Transaction

from app.controllers import crud
from app.controllers.business_controller import find_business
from app.controllers.crud import bad_request, forbidden, not_found
from app.controllers.customer_price_controller import list_prices_for_customer
from app.controllers.delivery_zone_controller import list_delivery_zones
from app.controllers.inventory_controller import calculate_stock
from app.controllers.payment_method_controller import list_accepted_payment_types, list_payment_methods
from app.controllers.pricing import calculate_delivery_fee, check_order_rules, find_unit_price
from app.controllers.product_controller import list_prices
from app.controllers.settings_controller import get_delivery, get_payment_terms
from app.core import cache
from app.dependencies.business_access import BusinessAccess
from app.models.business import Business
from app.models.inventory import InventoryItem, inventory_document
from app.models.product import Product, Variant, products_collection, variants_collection
from app.models.profile import locations_collection
from app.models.trade import Order, OrderItem, orders_collection
from app.schemas.enums import (
    ActiveStatus,
    BusinessStatus,
    DeliveryStatus,
    OrderStatus,
    Permission,
    ProductStatus,
    Visibility,
)
from app.schemas.order import OrderChargesIn, OrderIn, OrderStatusIn, PaymentStatusIn, Quote, QuoteLine
from app.schemas.views import OrderView
from app.schemas.payment import PaymentInstructions
from app.utils.helpers import current_time_ms

# Which status changes each side may make: {current status: [allowed next statuses]}
SELLER_CHANGES = {
    OrderStatus.PENDING: [OrderStatus.CONFIRMED, OrderStatus.REJECTED],
    OrderStatus.CONFIRMED: [OrderStatus.SHIPPED, OrderStatus.CANCELLED],
    OrderStatus.SHIPPED: [OrderStatus.DELIVERED],
}
BUYER_CHANGES = {
    OrderStatus.PENDING: [OrderStatus.CANCELLED],
    OrderStatus.DELIVERED: [OrderStatus.COMPLETED],
}

# ---- Quote (price check before ordering) ----------------------------------------------------


def build_quote(db: Client, buyer: Business, seller: Business, order_in: OrderIn) -> Quote:
    """Works out prices, delivery fee, and total. Anything that would block the order goes in `problems`."""
    problems: list[str] = []
    if seller.id == buyer.id:
        problems.append("You cannot order from your own business.")
    if seller.business_status != BusinessStatus.ACTIVE:
        problems.append("This seller is not accepting orders.")

    today = datetime.date.today()
    customer_prices = list_prices_for_customer(db, seller.id, buyer.id)
    lines: list[QuoteLine] = []

    for item in order_in.items:
        product = crud.find_document(products_collection(db, seller.id), item.product_id, Product)
        if product is None:
            problems.append("A product in your order no longer exists.")
            continue
        name = product.product_name
        if product.visibility != Visibility.PUBLIC or product.status != ProductStatus.ACTIVE:
            problems.append(f"{name} is not available.")
            continue

        variant = None
        if item.variant_id:
            variant = crud.find_document(variants_collection(db, seller.id, product.id), item.variant_id, Variant)
            if variant is None or variant.status != ActiveStatus.ACTIVE:
                problems.append(f"{name}: this option is not available.")
                continue
            name = f"{product.product_name} ({variant.variant_name})"

        unit = (variant.unit if variant and variant.unit else product.unit) or "pcs"
        unit_price = find_unit_price(
            list_prices(db, seller.id, product.id),
            [cp for cp in customer_prices if cp.product_id == product.id],
            item.variant_id,
            item.quantity,
            buyer.business_types,
            seller.currency,
            today,
        )
        if unit_price is None:
            problems.append(f"{name}: no price for {item.quantity} {unit}.")

        problems.extend(check_order_rules(product.order_rules, item.quantity, name))
        subtotal = round((unit_price or 0) * item.quantity, 2)
        min_value = product.order_rules.minimum_order_value
        if unit_price is not None and min_value and subtotal < min_value:
            problems.append(f"{name}: minimum order value is {min_value:,.2f}.")

        lines.append(
            QuoteLine(
                product_id=product.id,
                variant_id=item.variant_id,
                product_name=product.product_name,
                variant_name=variant.variant_name if variant else "",
                sku=(variant.sku if variant and variant.sku else product.sku),
                unit=unit,
                quantity=item.quantity,
                unit_price=unit_price,
                subtotal=subtotal,
            )
        )

    subtotal = round(sum(line.subtotal for line in lines), 2)
    delivery_fee, delivery_problems = calculate_delivery_fee(
        get_delivery(db, seller.id),
        list_delivery_zones(db, seller.id),
        order_in.fulfillment_method,
        order_in.shipping_address,
        subtotal,
    )
    problems.extend(delivery_problems)

    accepted_types = list_accepted_payment_types(db, seller.id)
    if order_in.payment_method_type and accepted_types and order_in.payment_method_type not in accepted_types:
        problems.append("This seller does not accept that payment method.")
    offered_terms = get_payment_terms(db, seller.id).payment_terms
    if order_in.payment_term and offered_terms and order_in.payment_term not in offered_terms:
        problems.append("This seller does not offer that payment term.")

    return Quote(
        lines=lines,
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        total=round(subtotal + delivery_fee, 2),
        currency=seller.currency,
        problems=problems,
    )


def quote_order(db: Client, access: BusinessAccess, order_in: OrderIn) -> Quote:
    seller = find_business(db, order_in.seller_business_id)
    if seller is None:
        raise not_found("Seller")
    return build_quote(db, access.business, seller, order_in)


# ---- Placing and reading orders --------------------------------------------------------


def create_order(db: Client, access: BusinessAccess, order_in: OrderIn) -> Order:
    """The buyer places an order. The server works out every price; the buyer only sends quantities."""
    access.require(Permission.PLACE_ORDERS)
    seller = find_business(db, order_in.seller_business_id)
    if seller is None:
        raise not_found("Seller")

    quote = build_quote(db, access.business, seller, order_in)
    if quote.problems:
        raise bad_request(" ".join(quote.problems))

    now = current_time_ms()
    order_ref = orders_collection(db).document()
    order = Order(
        id=order_ref.id,
        order_number=f"ORD-{datetime.date.today():%Y%m%d}-{order_ref.id[:5].upper()}",
        buyer_business_id=access.business_id,
        buyer_business_name=access.business.business_name,
        seller_business_id=seller.id,
        seller_business_name=seller.business_name,
        business_ids=[access.business_id, seller.id],
        placed_by_uid=access.user.uid,
        items=[OrderItem(**line.model_dump()) for line in quote.lines],
        currency=quote.currency,
        subtotal=quote.subtotal,
        delivery_fee=quote.delivery_fee,
        total=quote.total,
        fulfillment_method=order_in.fulfillment_method,
        shipping_address=order_in.shipping_address,
        payment_method_type=order_in.payment_method_type,
        payment_term=order_in.payment_term,
        notes=order_in.notes,
        ordered_at=now,
        created_at=now,
        updated_at=now,
    )
    order_ref.set(order.to_firestore())
    _clear_cache(order)
    return order


def _clear_cache(order: Order) -> None:
    """An order belongs to two businesses, so both cached copies are now outdated."""
    cache.bump(*[cache.business_scope(business_id) for business_id in order.business_ids])


def list_orders(db: Client, access: BusinessAccess, side: str | None = None) -> list[Order]:
    """Orders this business is part of, newest first. side = "buying", "selling", or None for both."""

    def read() -> list[Order]:
        query = orders_collection(db).where(filter=FieldFilter("businessIds", "array_contains", access.business_id))
        return [Order.from_snapshot(snapshot) for snapshot in query.stream()]

    orders = cache.cached_models(cache.business_scope(access.business_id), "orders", Order, read)
    if side == "buying":
        orders = [o for o in orders if o.buyer_business_id == access.business_id]
    elif side == "selling":
        orders = [o for o in orders if o.seller_business_id == access.business_id]
    return sorted(orders, key=lambda order: order.ordered_at, reverse=True)


def get_order(db: Client, access: BusinessAccess, order_id: str, fresh: bool = False) -> Order:
    """An order this business is the buyer or seller of, or 404.

    fresh=True skips the cache: use it before changing the order.
    """

    def read() -> Order | None:
        snapshot = orders_collection(db).document(order_id).get()
        return Order.from_snapshot(snapshot) if snapshot.exists else None

    order = read() if fresh else cache.cached_model(cache.business_scope(access.business_id), f"order:{order_id}", Order, read)
    if order is None or access.business_id not in order.business_ids:
        raise not_found("Order")
    return order


def get_order_view(db: Client, access: BusinessAccess, order_id: str) -> OrderView:
    """The order plus payment instructions for the buyer, once the seller has confirmed it."""
    order = get_order(db, access, order_id)
    view = OrderView(**order.model_dump())

    is_buyer = order.buyer_business_id == access.business_id
    confirmed = order.order_status not in (OrderStatus.PENDING, OrderStatus.REJECTED, OrderStatus.CANCELLED)
    if is_buyer and confirmed and order.payment_method_type:
        view.payment_instructions = [
            PaymentInstructions.model_validate(method)
            for method in list_payment_methods(db, order.seller_business_id)
            if method.is_active and method.payment_type == order.payment_method_type
        ]
    return view


# ---- Changing an order -------------------------------------------------------------------


def change_order_status(db: Client, access: BusinessAccess, order_id: str, status_in: OrderStatusIn) -> Order:
    order = get_order(db, access, order_id, fresh=True)
    is_seller = order.seller_business_id == access.business_id
    access.require(Permission.MANAGE_SALES_ORDERS if is_seller else Permission.PLACE_ORDERS)

    allowed = (SELLER_CHANGES if is_seller else BUYER_CHANGES).get(order.order_status, [])
    if status_in.status not in allowed:
        side = "seller" if is_seller else "buyer"
        raise bad_request(f"As the {side}, you cannot change this order from {order.order_status} to {status_in.status}")

    if status_in.status == OrderStatus.CONFIRMED:
        location_id = status_in.fulfillment_location_id
        if not location_id or not locations_collection(db, access.business_id).document(location_id).get().exists:
            raise bad_request("Choose the location the stock will come from")

    order_ref = orders_collection(db).document(order_id)
    updated = _change_status(db.transaction(), db, order_ref, order.order_status, status_in)
    _clear_cache(updated)
    return updated


@firestore.transactional
def _change_status(
    transaction: Transaction, db: Client, order_ref: DocumentReference, expected_status: OrderStatus, status_in: OrderStatusIn
) -> Order:
    # In a transaction, all reads must happen before any writes.
    order = Order.from_snapshot(order_ref.get(transaction=transaction))
    if order.order_status != expected_status:
        raise bad_request("Someone else just changed this order. Refresh and try again.")

    old_status, new_status = order.order_status, status_in.status
    location_id = status_in.fulfillment_location_id or order.fulfillment_location_id

    # 1. Work out the stock changes (if any) and read the stock records
    stock_updates: list[tuple[DocumentReference, InventoryItem]] = []
    touches_stock = new_status in (OrderStatus.CONFIRMED, OrderStatus.SHIPPED) or (
        new_status == OrderStatus.CANCELLED and old_status == OrderStatus.CONFIRMED
    )
    if touches_stock:
        # Add up quantities per stock record (the same product can appear on two lines)
        quantity_by_ref: dict[str, int] = defaultdict(int)
        refs: dict[str, DocumentReference] = {}
        names: dict[str, str] = {}
        for item in order.items:
            ref = inventory_document(db, order.seller_business_id, item.product_id, item.variant_id, location_id)
            refs[ref.id] = ref
            quantity_by_ref[ref.id] += item.quantity
            names[ref.id] = f"{item.product_name} {item.variant_name}".strip()

        for ref_id, ref in refs.items():
            snapshot = ref.get(transaction=transaction)
            quantity = quantity_by_ref[ref_id]
            if not snapshot.exists:
                if new_status == OrderStatus.CANCELLED:
                    continue  # stock record was deleted; nothing to release
                raise bad_request(f"{names[ref_id]} has no stock record at this location")
            stock = InventoryItem.from_snapshot(snapshot)

            if new_status == OrderStatus.CONFIRMED:
                if stock.available_quantity < quantity:
                    raise bad_request(f"Not enough {names[ref_id]}: {stock.available_quantity:g} available, {quantity} needed")
                stock.reserved_quantity += quantity
            elif new_status == OrderStatus.SHIPPED:
                stock.quantity -= quantity
                stock.reserved_quantity = max(stock.reserved_quantity - quantity, 0)
            else:  # cancelling a confirmed order
                stock.reserved_quantity = max(stock.reserved_quantity - quantity, 0)

            stock.updated_at = current_time_ms()
            stock_updates.append((ref, calculate_stock(stock)))

    # 2. Update the order
    now = current_time_ms()
    order.order_status = new_status
    order.updated_at = now
    if new_status == OrderStatus.CONFIRMED:
        order.confirmed_at = now
        order.fulfillment_location_id = location_id
    elif new_status == OrderStatus.SHIPPED:
        order.shipped_at = now
        order.delivery_status = DeliveryStatus.SHIPPED
    elif new_status == OrderStatus.DELIVERED:
        order.delivered_at = now
        order.delivery_status = DeliveryStatus.DELIVERED
    elif new_status == OrderStatus.COMPLETED:
        order.completed_at = now
    elif new_status in (OrderStatus.CANCELLED, OrderStatus.REJECTED):
        order.cancelled_at = now
        order.status_reason = status_in.reason

    # 3. Write everything
    for ref, stock in stock_updates:
        transaction.set(ref, stock.to_firestore())
    transaction.set(order_ref, order.to_firestore())
    return order


def change_payment_status(db: Client, access: BusinessAccess, order_id: str, payment_in: PaymentStatusIn) -> Order:
    """The seller records payment (e.g. after seeing the bank transfer)."""
    order = get_order(db, access, order_id, fresh=True)
    if order.seller_business_id != access.business_id:
        raise bad_request("Only the seller can change the payment status")
    if not (access.can(Permission.MANAGE_SALES_ORDERS) or access.can(Permission.MANAGE_PAYMENTS)):
        raise forbidden("You need the 'orders.sell' or 'payments.manage' permission to do this")

    order.payment_status = payment_in.payment_status
    order.updated_at = current_time_ms()
    orders_collection(db).document(order_id).update(
        {"paymentStatus": order.payment_status.value, "updatedAt": order.updated_at}
    )
    _clear_cache(order)
    return order


def change_order_charges(db: Client, access: BusinessAccess, order_id: str, charges_in: OrderChargesIn) -> Order:
    """The seller adjusts delivery fee, tax, or discount before confirming."""
    order = get_order(db, access, order_id, fresh=True)
    if order.seller_business_id != access.business_id:
        raise bad_request("Only the seller can change the charges")
    access.require(Permission.MANAGE_SALES_ORDERS)
    if order.order_status != OrderStatus.PENDING:
        raise bad_request("Charges can only be changed while the order is pending")

    order.delivery_fee = charges_in.delivery_fee
    order.tax = charges_in.tax
    order.discount = charges_in.discount
    order.total = round(max(order.subtotal + order.delivery_fee + order.tax - order.discount, 0), 2)
    order.updated_at = current_time_ms()
    orders_collection(db).document(order_id).set(order.to_firestore())
    _clear_cache(order)
    return order
