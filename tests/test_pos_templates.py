"""Selling app templates: the business picks how the till looks; selling works the same."""

import datetime
from types import SimpleNamespace

from app.controllers import pos_controller
from app.models.category import Category
from app.schemas.pos import CheckoutIn, PosProduct
from tests.conftest import login_as
from tests.test_pos import TODAY, checkout, shop  # noqa: F401 (shop is a fixture)


def test_catalog_gets_category_names(monkeypatch):
    """Names are added after the cached catalog is read, so a renamed category shows at once."""
    monkeypatch.setattr(pos_controller, "_build_catalog", lambda db, access, today: [
        PosProduct(id="p1", product_name="Latte", category_id="c1"),
        PosProduct(id="p2", product_name="Mystery"),
    ])
    monkeypatch.setattr(pos_controller, "list_categories", lambda db: [Category(id="c1", category_name="Coffee")])
    catalog = pos_controller.get_catalog(None, SimpleNamespace(business_id="b1"), datetime.date(2026, 10, 2))
    assert [(p.product_name, p.category_name) for p in catalog] == [("Latte", "Coffee"), ("Mystery", "")]


def test_order_details_are_checked():
    order = CheckoutIn(
        location_id="l1",
        items=[{"productId": "p1", "quantity": 1}],
        date=TODAY,
        order_type="DINE_IN",
        table_number="12",
        customer_name="Ana",
    )
    assert (order.order_type, order.table_number) == ("DINE_IN", "12")


def test_template_and_order_details_through_the_api(client, shop):
    """With the Firestore emulator: the owner picks Restaurant; a dine-in sale keeps its table number."""
    business_id = shop["business_id"]
    assert client.get(f"/api/v1/businesses/{business_id}/pos-settings").json()["template"] == "DEFAULT"
    saved = client.put(f"/api/v1/businesses/{business_id}/pos-settings", json={"template": "RESTAURANT"})
    assert saved.status_code == 200, saved.text

    login_as("seller@test.com")
    assert client.get(f"/api/v1/businesses/{business_id}/pos/context").json()["template"] == "RESTAURANT"
    receipt = checkout(client, shop, 2, orderType="DINE_IN", tableNumber=" 7 ").json()
    assert (receipt["orderType"], receipt["tableNumber"]) == ("DINE_IN", "7")

    # Sellers cannot change the template (only people who can edit the business)
    assert client.put(f"/api/v1/businesses/{business_id}/pos-settings", json={"template": "GROCERY"}).status_code == 403


def test_a_custom_template_is_tidied():
    from app.schemas.pos import PosCustomTemplate

    custom = PosCustomTemplate(order_types=["TAKE_OUT", "TAKE_OUT", "DELIVERY"], table_number=True, customer_name=True)
    assert custom.order_types == ["TAKE_OUT", "DELIVERY"]
    assert custom.table_number is False  # no dine-in, so no table to ask for
    assert PosCustomTemplate(order_types=["DINE_IN"], table_number=True).table_number is True


def test_the_till_gets_the_custom_switches_only_when_they_are_used():
    from app.models.settings import PosSettings
    from app.schemas.pos import PosCustomTemplate

    own = PosCustomTemplate(name="Milk tea shop", layout="list")
    assert pos_controller._template(PosSettings(template="CUSTOM", custom=own))["custom"].name == "Milk tea shop"
    assert pos_controller._template(PosSettings(template="GROCERY", custom=own)) == {"template": "GROCERY", "custom": None}
