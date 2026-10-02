"""The full buying flow between two businesses."""

from tests.conftest import create_business, create_product_with_stock, login_as


def setup_seller_and_buyer(client, stock=100):
    seller_id = create_business(client, "Acme Supplies", ["SUPPLIER"])["id"]
    product_id, location_id = create_product_with_stock(client, seller_id, stock)
    login_as("buyer@test.com")
    buyer_id = create_business(client, "Corner Store", ["RETAILER"])["id"]
    return seller_id, buyer_id, product_id, location_id


def order_body(seller_id, product_id, quantity):
    return {
        "sellerBusinessId": seller_id,
        "items": [{"productId": product_id, "quantity": quantity}],
        "fulfillmentMethod": "PICKUP",
    }


def stock_of(client, seller_id):
    return client.get(f"/api/v1/businesses/{seller_id}/inventory").json()[0]


def test_quote_shows_price_tier_and_problems(client):
    seller_id, buyer_id, product_id, _ = setup_seller_and_buyer(client)

    quote = client.post(f"/api/v1/businesses/{buyer_id}/orders/quote", json=order_body(seller_id, product_id, 50)).json()
    assert quote["lines"][0]["unitPrice"] == 100
    assert quote["total"] == 5000
    assert quote["problems"] == []

    quote = client.post(f"/api/v1/businesses/{buyer_id}/orders/quote", json=order_body(seller_id, product_id, 7)).json()
    assert "minimum order is 10" in " ".join(quote["problems"])

    response = client.post(f"/api/v1/businesses/{buyer_id}/orders", json=order_body(seller_id, product_id, 7))
    assert response.status_code == 400


def test_order_life_cycle_moves_stock(client):
    seller_id, buyer_id, product_id, location_id = setup_seller_and_buyer(client, stock=100)

    order = client.post(f"/api/v1/businesses/{buyer_id}/orders", json=order_body(seller_id, product_id, 20)).json()
    assert order["orderStatus"] == "PENDING"
    assert order["total"] == 2400

    # Seller accepts: the 20 are taken out right away
    login_as("owner@test.com")
    assert [o["id"] for o in client.get(f"/api/v1/businesses/{seller_id}/orders?side=selling").json()] == [order["id"]]
    response = client.post(
        f"/api/v1/businesses/{seller_id}/orders/{order['id']}/status",
        json={"status": "CONFIRMED", "fulfillmentLocationId": location_id},
    )
    assert response.status_code == 200, response.text
    stock = stock_of(client, seller_id)
    assert (stock["quantity"], stock["reservedQuantity"], stock["availableQuantity"]) == (80, 0, 80)

    # Seller ships: the stock was already taken out when accepting
    client.post(f"/api/v1/businesses/{seller_id}/orders/{order['id']}/status", json={"status": "SHIPPED"})
    stock = stock_of(client, seller_id)
    assert (stock["quantity"], stock["reservedQuantity"]) == (80, 0)

    client.post(f"/api/v1/businesses/{seller_id}/orders/{order['id']}/status", json={"status": "DELIVERED"})

    # The seller cannot complete the order; the buyer does
    response = client.post(f"/api/v1/businesses/{seller_id}/orders/{order['id']}/status", json={"status": "COMPLETED"})
    assert response.status_code == 400
    login_as("buyer@test.com")
    response = client.post(f"/api/v1/businesses/{buyer_id}/orders/{order['id']}/status", json={"status": "COMPLETED"})
    assert response.json()["orderStatus"] == "COMPLETED"

    # Now the buyer can review the seller, once
    review = {"ratings": {"productQuality": 5, "delivery": 4}, "review": "Great!"}
    assert client.post(f"/api/v1/businesses/{buyer_id}/orders/{order['id']}/review", json=review).status_code == 201
    assert client.post(f"/api/v1/businesses/{buyer_id}/orders/{order['id']}/review", json=review).status_code == 400

    seller = client.get("/api/v1/directory/businesses").json()
    acme = next(b for b in seller if b["id"] == seller_id)
    assert (acme["ratingAverage"], acme["ratingCount"]) == (4.5, 1)


def test_cannot_confirm_without_enough_stock(client):
    seller_id, buyer_id, product_id, location_id = setup_seller_and_buyer(client, stock=10)
    order = client.post(f"/api/v1/businesses/{buyer_id}/orders", json=order_body(seller_id, product_id, 50)).json()

    login_as("owner@test.com")
    response = client.post(
        f"/api/v1/businesses/{seller_id}/orders/{order['id']}/status",
        json={"status": "CONFIRMED", "fulfillmentLocationId": location_id},
    )
    assert response.status_code == 400
    assert "Not enough" in response.json()["detail"]


def test_cancelling_an_accepted_order_puts_the_stock_back(client):
    seller_id, buyer_id, product_id, location_id = setup_seller_and_buyer(client)
    order = client.post(f"/api/v1/businesses/{buyer_id}/orders", json=order_body(seller_id, product_id, 30)).json()

    login_as("owner@test.com")
    url = f"/api/v1/businesses/{seller_id}/orders/{order['id']}/status"
    client.post(url, json={"status": "CONFIRMED", "fulfillmentLocationId": location_id})
    client.post(url, json={"status": "CANCELLED", "reason": "Out of trucks"})

    stock = stock_of(client, seller_id)
    assert (stock["quantity"], stock["reservedQuantity"], stock["availableQuantity"]) == (100, 0, 100)


def test_customer_price_is_used_for_that_buyer(client):
    seller_id, buyer_id, product_id, _ = setup_seller_and_buyer(client)

    login_as("owner@test.com")
    response = client.post(
        f"/api/v1/businesses/{seller_id}/customer-prices",
        json={"customerBusinessId": buyer_id, "productId": product_id, "price": 95},
    )
    assert response.status_code == 201, response.text

    login_as("buyer@test.com")
    products = client.get(f"/api/v1/directory/businesses/{seller_id}/products?buyer_business_id={buyer_id}").json()
    assert products[0]["customerPrices"][0]["price"] == 95
    assert "costPrice" not in products[0]

    quote = client.post(f"/api/v1/businesses/{buyer_id}/orders/quote", json=order_body(seller_id, product_id, 10)).json()
    assert quote["lines"][0]["unitPrice"] == 95


def test_walk_in_sale_takes_stock(client):
    seller_id = create_business(client)["id"]
    product_id, location_id = create_product_with_stock(client, seller_id, stock=5)
    sale = {"productId": product_id, "locationId": location_id, "quantity": 3, "unitPrice": 130, "date": "2026-09-27"}

    sale_id = client.post(f"/api/v1/businesses/{seller_id}/sales", json=sale).json()["id"]
    assert stock_of(client, seller_id)["quantity"] == 2
    assert client.post(f"/api/v1/businesses/{seller_id}/sales", json=sale).status_code == 400  # only 2 left

    client.delete(f"/api/v1/businesses/{seller_id}/sales/{sale_id}")
    assert stock_of(client, seller_id)["quantity"] == 5
