"""The Redis cache: data is served from the cache, and every change makes it fresh again."""

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from app.core import cache
from tests.conftest import create_business, create_product_with_stock, login_as


def test_reads_are_served_from_the_cache(client, firestore_db):
    business_id = create_business(client)["id"]
    assert client.get(f"/api/v1/businesses/{business_id}/brands").json() == []

    # Change Firestore directly, behind the API's back: the cached (empty) list is still returned...
    firestore_db.collection("businesses").document(business_id).collection("brands").document("b1").set(
        {"brandName": "Sneaky", "status": "ACTIVE", "createdAt": 1, "updatedAt": 1}
    )
    assert client.get(f"/api/v1/businesses/{business_id}/brands").json() == []

    # ...until something changes through the API, which marks the business's cache as outdated
    client.post(f"/api/v1/businesses/{business_id}/brands", json={"brandName": "Fizzy"})
    names = [b["brandName"] for b in client.get(f"/api/v1/businesses/{business_id}/brands").json()]
    assert names == ["Sneaky", "Fizzy"]


def test_an_order_refreshes_the_other_business_too(client):
    seller_id = create_business(client, "Acme Supplies", ["SUPPLIER"])["id"]
    product_id, _ = create_product_with_stock(client, seller_id)
    assert client.get(f"/api/v1/businesses/{seller_id}/orders").json() == []  # now cached

    login_as("buyer@test.com")
    buyer_id = create_business(client, "Corner Store", ["RETAILER"])["id"]
    client.post(
        f"/api/v1/businesses/{buyer_id}/orders",
        json={"sellerBusinessId": seller_id, "items": [{"productId": product_id, "quantity": 10}], "fulfillmentMethod": "PICKUP"},
    )

    # The order was placed through the BUYER's URL, but the seller's cached list is refreshed as well
    login_as("owner@test.com")
    assert len(client.get(f"/api/v1/businesses/{seller_id}/orders").json()) == 1


def test_directory_refreshes_after_a_profile_change(client):
    business_id = create_business(client, "Old Name")["id"]
    assert [b["businessName"] for b in client.get("/api/v1/directory/businesses").json()] == ["Old Name"]

    client.put(f"/api/v1/businesses/{business_id}", json={"businessName": "New Name", "businessTypes": ["SUPPLIER"]})
    assert [b["businessName"] for b in client.get("/api/v1/directory/businesses").json()] == ["New Name"]


def test_everything_still_works_when_redis_is_down(client):
    # A Redis address where nothing is listening
    cache.set_client(
        redis.Redis(host="127.0.0.1", port=1, socket_timeout=0.2, socket_connect_timeout=0.2, retry=Retry(NoBackoff(), 0))
    )

    business_id = create_business(client)["id"]
    response = client.post(f"/api/v1/businesses/{business_id}/brands", json={"brandName": "Fizzy"})
    assert response.status_code == 201
    assert [b["brandName"] for b in client.get(f"/api/v1/businesses/{business_id}/brands").json()] == ["Fizzy"]


def test_nothing_stale_survives_an_outage(client, firestore_db, fake_redis, monkeypatch):
    business_id = create_business(client)["id"]
    assert client.get(f"/api/v1/businesses/{business_id}/brands").json() == []  # cached

    # Redis "goes down": changes made now cannot mark the cache as outdated
    cache._pause(redis.ConnectionError("test outage"))
    firestore_db.collection("businesses").document(business_id).collection("brands").document("b1").set(
        {"brandName": "Added during outage", "status": "ACTIVE", "createdAt": 1, "updatedAt": 1}
    )

    # Redis "comes back": the old cache is thrown away, so the change is visible
    monkeypatch.setattr(cache, "_offline_until", 0.0)
    names = [b["brandName"] for b in client.get(f"/api/v1/businesses/{business_id}/brands").json()]
    assert names == ["Added during outage"]


def test_business_context_returns_business_and_role(client):
    business_id = create_business(client)["id"]
    context = client.get(f"/api/v1/businesses/{business_id}/context").json()
    assert context["business"]["id"] == business_id
    assert context["role"]["role"] == "OWNER"


def test_all_variants_in_one_request(client):
    business_id = create_business(client)["id"]
    product_id, _ = create_product_with_stock(client, business_id)
    for name in ("290ml", "1.5L"):
        client.post(f"/api/v1/businesses/{business_id}/products/{product_id}/variants", json={"variantName": name})

    variants = client.get(f"/api/v1/businesses/{business_id}/variants").json()
    assert sorted(v["variantName"] for v in variants) == ["1.5L", "290ml"]
