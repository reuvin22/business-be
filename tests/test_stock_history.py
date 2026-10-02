"""Every change to a quantity on hand is written to the stock history."""

from tests.conftest import create_business, create_product_with_stock, login_as


def history(client, business_id, **params):
    response = client.get(f"/api/v1/businesses/{business_id}/stock-movements", params=params)
    assert response.status_code == 200, response.text
    # oldest first reads more naturally in a test
    return [(m["movementType"], m["change"], m["quantityAfter"]) for m in reversed(response.json())]


def test_every_stock_change_is_recorded(client):
    business_id = create_business(client)["id"]
    product_id, location_id = create_product_with_stock(client, business_id, stock=100)
    stock_id = client.get(f"/api/v1/businesses/{business_id}/inventory").json()[0]["id"]

    client.post(f"/api/v1/businesses/{business_id}/inventory/{stock_id}/adjust", json={"change": 20, "note": "Delivery"})
    client.put(f"/api/v1/businesses/{business_id}/inventory/{stock_id}", json={"quantity": 115, "reorderLevel": 10})
    sale = client.post(
        f"/api/v1/businesses/{business_id}/sales",
        json={"productId": product_id, "locationId": location_id, "quantity": 3, "unitPrice": 130, "date": "2026-09-27"},
    ).json()
    client.delete(f"/api/v1/businesses/{business_id}/sales/{sale['id']}")

    assert history(client, business_id) == [
        ("STOCK_ADDED", 100, 100),
        ("ADJUSTMENT", 20, 120),
        ("CORRECTION", -5, 115),
        ("SALE", -3, 112),
        ("SALE_UNDONE", 3, 115),
    ]

    latest = client.get(f"/api/v1/businesses/{business_id}/stock-movements").json()[0]
    assert latest["productName"] == "Cola 1.5L"
    assert latest["locationName"] == "Main warehouse"
    assert latest["byName"] == "owner"


def test_accepting_an_order_is_recorded(client):
    seller_id = create_business(client, "Acme Supplies", ["SUPPLIER"])["id"]
    product_id, location_id = create_product_with_stock(client, seller_id, stock=50)

    login_as("buyer@test.com")
    buyer_id = create_business(client, "Corner Store", ["RETAILER"])["id"]
    order = client.post(
        f"/api/v1/businesses/{buyer_id}/orders",
        json={"sellerBusinessId": seller_id, "items": [{"productId": product_id, "quantity": 10}], "fulfillmentMethod": "PICKUP"},
    ).json()

    login_as("owner@test.com")
    url = f"/api/v1/businesses/{seller_id}/orders/{order['id']}/status"
    client.post(url, json={"status": "CONFIRMED", "fulfillmentLocationId": location_id})
    # Accepting takes the stock out, with the order number on the history line
    assert history(client, seller_id)[-1] == ("ORDER_ACCEPTED", -10, 40)
    accepted = client.get(f"/api/v1/businesses/{seller_id}/stock-movements").json()[0]
    assert accepted["referenceLabel"] == order["orderNumber"]

    # Shipping changes nothing more: the stock already left when the order was accepted
    client.post(url, json={"status": "SHIPPED"})
    assert history(client, seller_id)[-1] == ("ORDER_ACCEPTED", -10, 40)


def test_filter_history_by_product_and_removing_a_record(client):
    business_id = create_business(client)["id"]
    product_id, _ = create_product_with_stock(client, business_id, stock=7)
    stock_id = client.get(f"/api/v1/businesses/{business_id}/inventory").json()[0]["id"]

    client.delete(f"/api/v1/businesses/{business_id}/inventory/{stock_id}")
    assert history(client, business_id, product_id=product_id) == [("STOCK_ADDED", 7, 7), ("RECORD_REMOVED", -7, 0)]
    assert history(client, business_id, product_id="some-other-product") == []
