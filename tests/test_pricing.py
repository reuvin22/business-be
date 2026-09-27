"""The price and delivery rules are plain functions, so they are tested without the database."""

import datetime

from app.controllers.pricing import calculate_delivery_fee, check_order_rules, find_unit_price
from app.models.network import CustomerPrice
from app.models.product import Price
from app.models.profile import DeliveryZone
from app.models.settings import DeliverySettings
from app.schemas.order import Address
from app.schemas.product import OrderRules

TODAY = datetime.date(2026, 9, 27)
TIERS = [
    Price(price=120, minimum_quantity=1, maximum_quantity=9),
    Price(price=110, minimum_quantity=10, maximum_quantity=49),
    Price(price=100, minimum_quantity=50),
    Price(price=90, minimum_quantity=50, customer_type="DISTRIBUTOR"),
]


def price_for(quantity, buyer_types=("RETAILER",), customer_prices=(), variant_id=None, prices=TIERS):
    return find_unit_price(list(prices), list(customer_prices), variant_id, quantity, list(buyer_types), "PHP", TODAY)


def test_quantity_picks_the_tier():
    assert price_for(1) == 120
    assert price_for(10) == 110
    assert price_for(50) == 100


def test_customer_type_tier_only_for_that_type():
    assert price_for(50, buyer_types=["RETAILER"]) == 100
    assert price_for(50, buyer_types=["DISTRIBUTOR"]) == 90


def test_customer_price_wins():
    special = CustomerPrice(customer_business_id="b", product_id="p", price=95, minimum_quantity=1)
    assert price_for(1, customer_prices=[special]) == 95


def test_expired_prices_are_ignored():
    old = Price(price=50, minimum_quantity=1, effective_until=datetime.date(2026, 1, 1))
    assert price_for(1, prices=[old]) is None


def test_variant_prices_replace_product_prices():
    prices = TIERS + [Price(price=200, minimum_quantity=1, variant_id="big")]
    assert price_for(60, variant_id="big", prices=prices) == 200
    assert price_for(60, variant_id="small", prices=prices) == 100


def test_order_rules():
    rules = OrderRules(minimum_order_quantity=50, order_multiple=10)
    assert check_order_rules(rules, 60, "Cola") == []
    assert len(check_order_rules(rules, 20, "Cola")) == 1  # below MOQ
    assert len(check_order_rules(rules, 55, "Cola")) == 1  # not a multiple of 10


def test_delivery_fee_uses_the_most_specific_zone_and_free_threshold():
    delivery = DeliverySettings(delivery_available=True, delivery_fee=300, free_delivery_threshold=10000)
    zones = [DeliveryZone(province="Metro Manila", delivery_fee=150), DeliveryZone(city="Pasig", delivery_fee=80)]
    pasig = Address(city="Pasig", province="Metro Manila")

    assert calculate_delivery_fee(delivery, zones, "DELIVERY", pasig, 1000) == (80, [])
    assert calculate_delivery_fee(delivery, zones, "DELIVERY", Address(city="Makati", province="Metro Manila"), 1000) == (150, [])
    assert calculate_delivery_fee(delivery, zones, "DELIVERY", pasig, 20000) == (0, [])
    fee, problems = calculate_delivery_fee(delivery, zones, "DELIVERY", Address(city="Cebu City", province="Cebu"), 1000)
    assert problems == ["This seller does not deliver to Cebu City."]
