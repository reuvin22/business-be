"""The selling app: seller accounts, checkout, voiding, and stock changes at the counter."""

import pytest

from tests.conftest import ACCOUNTS, create_business, create_product_with_stock, login_as

TODAY = "2026-09-28"


@pytest.fixture
def shop(client, monkeypatch):
    """A business with a product in stock (100 boxes, 120 each below 50), and a seller at its warehouse."""
    monkeypatch.setattr(
        "app.controllers.seller_controller.create_account",
        lambda email, password, name: {"uid": ACCOUNTS[email], "email": email, "display_name": name},
    )
    monkeypatch.setattr("app.controllers.seller_controller.set_account_name", lambda uid, name: None)
    monkeypatch.setattr("app.controllers.seller_controller.set_account_password", lambda uid, password: None)

    business_id = create_business(client)["id"]
    product_id, location_id = create_product_with_stock(client, business_id, stock=100)
    response = client.post(
        f"/api/v1/businesses/{business_id}/sellers",
        json={"displayName": "Ana", "email": "seller@test.com", "password": "secret123", "locationId": location_id},
    )
    assert response.status_code == 201, response.text
    return {"business_id": business_id, "product_id": product_id, "location_id": location_id}


def stock_quantity(client, shop) -> float:
    url = f"/api/v1/businesses/{shop['business_id']}/pos/stock"
    return client.get(url, params={"location_id": shop["location_id"]}).json()[0]["quantity"]


def checkout(client, shop, *quantities, **extra):
    return client.post(
        f"/api/v1/businesses/{shop['business_id']}/pos/checkouts",
        json={
            "locationId": shop["location_id"],
            "items": [{"productId": shop["product_id"], "quantity": q} for q in quantities],
            "date": TODAY,
            **extra,
        },
    )


def test_seller_only_uses_the_selling_app(client, shop):
    business_id = shop["business_id"]
    assert client.get(f"/api/v1/businesses/{business_id}/sellers").json()[0]["role"] == "SELLER"

    login_as("seller@test.com")
    assert client.get(f"/api/v1/businesses/{business_id}/products").status_code == 403
    assert client.get("/api/v1/businesses").json() == []  # not in the main app's list
    assert [b["id"] for b in client.get("/api/v1/pos/businesses").json()] == [business_id]

    context = client.get(f"/api/v1/businesses/{business_id}/pos/context").json()
    assert context["sellerName"] == "Ana"
    assert [loc["id"] for loc in context["locations"]] == [shop["location_id"]]

    catalog = client.get(f"/api/v1/businesses/{business_id}/pos/catalog", params={"date": TODAY}).json()
    assert catalog[0]["productName"] == "Cola 1.5L"
    assert {p["price"] for p in catalog[0]["prices"]} == {120, 100}


def test_checkout_totals_and_takes_stock_out(client, shop):
    login_as("seller@test.com")
    response = checkout(client, shop, 3, 2, amountPaid=1000)  # the same product twice becomes one line
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert [(line["quantity"], line["unitPrice"]) for line in receipt["items"]] == [(5, 120)]
    assert (receipt["total"], receipt["amountPaid"], receipt["changeGiven"]) == (600, 1000, 400)
    assert stock_quantity(client, shop) == 95

    # Not enough stock, or not enough money: nothing changes
    assert checkout(client, shop, 96).status_code == 400
    assert checkout(client, shop, 1, amountPaid=50).status_code == 400
    assert stock_quantity(client, shop) == 95

    login_as("owner@test.com")
    business_id = shop["business_id"]
    sale = client.get(f"/api/v1/businesses/{business_id}/sales").json()[0]
    assert sale["receiptNumber"] == receipt["receiptNumber"]
    movement = client.get(f"/api/v1/businesses/{business_id}/stock-movements").json()[0]
    assert (movement["movementType"], movement["change"], movement["byName"]) == ("SALE", -5, "seller")
    # Deleting it in the main app deletes the whole receipt and puts the stock back
    assert client.delete(f"/api/v1/businesses/{business_id}/sales/{sale['id']}").status_code == 204
    assert client.get(f"/api/v1/businesses/{business_id}/sales").json() == []
    assert client.get(f"/api/v1/businesses/{business_id}/pos/receipts", params={"date": TODAY}).json() == []
    assert stock_quantity(client, shop) == 100


def test_void_puts_stock_back(client, shop):
    login_as("seller@test.com")
    receipt = checkout(client, shop, 4).json()
    url = f"/api/v1/businesses/{shop['business_id']}/pos/receipts/{receipt['id']}/void"

    response = client.post(url, json={"reason": "Customer changed their mind"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "VOIDED"
    assert stock_quantity(client, shop) == 100
    assert client.post(url, json={"reason": "again"}).status_code == 400

    receipts = client.get(f"/api/v1/businesses/{shop['business_id']}/pos/receipts", params={"date": TODAY}).json()
    assert [r["status"] for r in receipts] == ["VOIDED"]

    login_as("owner@test.com")
    assert client.get(f"/api/v1/businesses/{shop['business_id']}/sales").json() == []


def test_seller_stays_at_their_store(client, shop):
    business_id = shop["business_id"]
    other = client.post(
        f"/api/v1/businesses/{business_id}/locations", json={"locationName": "Branch", "locationType": "STORE"}
    ).json()

    login_as("seller@test.com")
    response = client.post(
        f"/api/v1/businesses/{business_id}/pos/checkouts",
        json={"locationId": other["id"], "items": [{"productId": shop["product_id"], "quantity": 1}], "date": TODAY},
    )
    assert response.status_code == 403


def test_receiving_and_removing_stock(client, shop):
    login_as("seller@test.com")
    url = f"/api/v1/businesses/{shop['business_id']}/pos/stock-changes"
    base = {"locationId": shop["location_id"], "productId": shop["product_id"]}

    assert client.post(url, json={**base, "change": 24, "note": "Delivery"}).json()["quantity"] == 124
    assert client.post(url, json={**base, "change": -2}).status_code == 422  # removing needs a reason
    assert client.post(url, json={**base, "change": -2, "note": "Damaged"}).json()["quantity"] == 122

    history = client.get(
        f"/api/v1/businesses/{shop['business_id']}/pos/stock-history", params={"location_id": shop["location_id"]}
    ).json()
    assert [(m["change"], m["note"]) for m in history[:2]] == [(-2, "Damaged"), (24, "Delivery")]


def test_retail_prices_win_at_the_counter(client, shop):
    business_id, product_id = shop["business_id"], shop["product_id"]
    client.post(
        f"/api/v1/businesses/{business_id}/products/{product_id}/prices",
        json={"priceType": "RETAIL", "price": 150, "minimumQuantity": 1},
    )
    login_as("seller@test.com")
    assert checkout(client, shop, 2).json()["total"] == 300


def test_sellers_are_managed_apart_from_the_team(client, shop):
    business_id = shop["business_id"]
    response = client.post(f"/api/v1/businesses/{business_id}/members", json={"email": "staff@test.com", "role": "SELLER"})
    assert response.status_code == 400

    seller_url = f"/api/v1/businesses/{business_id}/sellers/seller-uid"
    response = client.put(seller_url, json={"displayName": "Ana", "locationId": None, "status": "SUSPENDED"})
    assert response.status_code == 200, response.text
    assert client.put(f"{seller_url}/password", json={"password": "newpass1"}).status_code == 204

    login_as("seller@test.com")
    assert client.get("/api/v1/pos/businesses").json() == []
    assert client.get(f"/api/v1/businesses/{business_id}/pos/context").status_code == 404


def test_counter_prices_like_a_shop(client, shop):
    """Tiers stop at 49, then 50+. Buying above a tier's "to quantity" keeps a price, and a product
    whose only price is for one kind of buyer can still be sold to a walk-in customer."""
    business_id = shop["business_id"]
    product = client.post(f"/api/v1/businesses/{business_id}/products/full", json={
        "productName": "Tube 275x18", "unit": "pc",
        "prices": [{"price": 150, "maximumQuantity": 10, "customerType": "RETAILER", "priceType": "RETAIL"}],
    }).json()["product"]
    client.post(f"/api/v1/businesses/{business_id}/inventory",
                json={"productId": product["id"], "locationId": shop["location_id"], "quantity": 50})

    login_as("seller@test.com")
    response = client.post(f"/api/v1/businesses/{business_id}/pos/checkouts", json={
        "locationId": shop["location_id"], "date": TODAY,
        "items": [{"productId": product["id"], "quantity": 12}],  # more than the tier's 10
    })
    assert response.status_code == 201, response.text
    assert response.json()["total"] == 1800


def test_deleting_a_voided_receipt_keeps_stock(client, shop):
    login_as("seller@test.com")
    receipt = checkout(client, shop, 5).json()
    base = f"/api/v1/businesses/{shop['business_id']}/pos/receipts/{receipt['id']}"
    client.post(f"{base}/void", json={"reason": "Wrong item"})
    assert client.delete(base).status_code == 403  # sellers cannot delete receipts

    login_as("owner@test.com")
    assert client.delete(base).status_code == 204
    assert stock_quantity(client, shop) == 100  # put back once (by the void), not twice
