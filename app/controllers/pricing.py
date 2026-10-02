"""Price and delivery-fee rules. Plain functions with no database access, so they are easy to test.

Used by order_controller to build a quote (and the order itself).
"""

import datetime

from app.models.network import CustomerPrice
from app.models.product import Price
from app.models.profile import DeliveryZone
from app.models.settings import DeliverySettings
from app.schemas.enums import ActiveStatus, BusinessType, FulfillmentMethod
from app.schemas.order import Address
from app.schemas.product import OrderRules


def is_current(start: datetime.date | None, end: datetime.date | None, today: datetime.date) -> bool:
    """True when today is inside the (optional) date range."""
    return (start is None or start <= today) and (end is None or today <= end)


def find_unit_price(
    prices: list[Price],
    customer_prices: list[CustomerPrice],
    variant_id: str | None,
    quantity: int,
    buyer_types: list[BusinessType],
    currency: str,
    today: datetime.date,
) -> float | None:
    """The price per unit for one order line, or None when no price applies.

    1. A private customer price for this buyer wins (the lowest one that applies).
    2. Otherwise the price tiers are used: the variant's own tiers if it has any,
       else the product-wide tiers. Of the tiers that fit the quantity, the buyer's
       business type, and today's date, the lowest price is used.
    """
    customer_options = [
        cp.price
        for cp in customer_prices
        if cp.variant_id in (None, variant_id)
        and quantity >= cp.minimum_quantity
        and is_current(cp.effective_from, cp.effective_until, today)
    ]
    if customer_options:
        return min(customer_options)

    usable = [
        p
        for p in prices
        if p.status == ActiveStatus.ACTIVE
        and p.currency == currency
        and is_current(p.effective_from, p.effective_until, today)
    ]
    variant_tiers = [p for p in usable if variant_id and p.variant_id == variant_id]
    tiers = variant_tiers or [p for p in usable if p.variant_id is None]

    matching = [
        p.price
        for p in tiers
        if p.minimum_quantity <= quantity
        and (p.maximum_quantity is None or quantity <= p.maximum_quantity)
        and (p.customer_type is None or p.customer_type in buyer_types)
    ]
    return min(matching) if matching else None


def check_order_rules(rules: OrderRules, quantity: int, name: str) -> list[str]:
    """Problems with the quantity of one line, e.g. below the minimum order quantity (MOQ)."""
    problems = []
    if quantity < rules.minimum_order_quantity:
        problems.append(f"{name}: minimum order is {rules.minimum_order_quantity}.")
    if rules.maximum_order_quantity and quantity > rules.maximum_order_quantity:
        problems.append(f"{name}: maximum order is {rules.maximum_order_quantity}.")
    if quantity % rules.order_multiple != 0:
        problems.append(f"{name}: order in multiples of {rules.order_multiple}.")
    return problems


def find_delivery_zone(zones: list[DeliveryZone], address: Address) -> DeliveryZone | None:
    """The zone that matches the address. The most specific wins: barangay > city > province > region > country."""

    def matches(zone: DeliveryZone) -> bool:
        for field in ("country", "region", "province", "city", "barangay"):
            zone_value = getattr(zone, field)
            if zone_value and zone_value.strip().lower() != getattr(address, field).strip().lower():
                return False
        return True

    def specificity(zone: DeliveryZone) -> tuple:
        return (bool(zone.barangay), bool(zone.city), bool(zone.province), bool(zone.region), bool(zone.country))

    matching = [zone for zone in zones if matches(zone)]
    return max(matching, key=specificity) if matching else None


def calculate_delivery_fee(
    delivery: DeliverySettings,
    zones: list[DeliveryZone],
    method: FulfillmentMethod,
    address: Address | None,
    subtotal: float,
) -> tuple[float, list[str]]:
    """Returns (fee, problems) for getting the order to the buyer."""
    if method == FulfillmentMethod.PICKUP:
        if not delivery.pickup_available:
            return 0, ["This seller does not offer pickup."]
        return 0, []

    if method == FulfillmentMethod.DELIVERY and not delivery.delivery_available:
        return 0, ["This seller does not offer delivery."]
    if method == FulfillmentMethod.SHIPPING and not delivery.shipping_available:
        return 0, ["This seller does not offer shipping."]
    if address is None or not address.city:
        return 0, ["Add a delivery address with at least a city."]

    problems = []
    if delivery.minimum_order_for_delivery and subtotal < delivery.minimum_order_for_delivery:
        problems.append(f"The minimum order for delivery is {delivery.minimum_order_for_delivery:,.2f}.")

    fee = delivery.delivery_fee or 0
    if method == FulfillmentMethod.DELIVERY and zones:
        zone = find_delivery_zone(zones, address)
        if zone is None:
            problems.append(f"This seller does not deliver to {address.city}.")
        else:
            fee = zone.delivery_fee

    if delivery.free_delivery_threshold is not None and subtotal >= delivery.free_delivery_threshold:
        fee = 0
    return fee, problems
