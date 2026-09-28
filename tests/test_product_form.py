"""The product form: a product, its variants, and its price tiers saved in one step."""

import pytest
from pydantic import ValidationError

from app.schemas.product import ProductFormIn
from tests.conftest import create_business

FORM = {
    "productName": "Cola",
    "unit": "bottle",
    "variants": [{"key": "new-1", "variantName": "290ml"}, {"key": "new-2", "variantName": "1.5L"}],
    "prices": [
        {"price": 20, "minimumQuantity": 1},  # whole product
        {"price": 65, "minimumQuantity": 1, "variantKey": "new-2"},  # only the 1.5L
    ],
}


def test_create_product_with_variants_and_prices(client):
    business_id = create_business(client)["id"]
    response = client.post(f"/api/v1/businesses/{business_id}/products/full", json=FORM)
    assert response.status_code == 201, response.text
    saved = response.json()

    assert saved["product"]["productName"] == "Cola"
    assert [v["variantName"] for v in saved["variants"]] == ["290ml", "1.5L"]
    big = saved["variants"][1]["id"]
    assert [(p["price"], p["variantId"]) for p in saved["prices"]] == [(20, None), (65, big)]
    assert all(p["currency"] == "PHP" for p in saved["prices"])

    # Reading it back gives the same thing, in the same order
    product_id = saved["product"]["id"]
    again = client.get(f"/api/v1/businesses/{business_id}/products/{product_id}/full").json()
    assert [v["variantName"] for v in again["variants"]] == ["290ml", "1.5L"]
    assert len(again["prices"]) == 2


def test_update_adds_changes_and_removes(client):
    business_id = create_business(client)["id"]
    saved = client.post(f"/api/v1/businesses/{business_id}/products/full", json=FORM).json()
    product_id = saved["product"]["id"]
    small, big = saved["variants"]
    whole_price = saved["prices"][0]

    form = {
        "productName": "Cola Classic",
        "unit": "bottle",
        # keep 290ml (renamed), drop 1.5L, add 2L
        "variants": [{"key": small["id"], "variantName": "300ml"}, {"key": "new-9", "variantName": "2L"}],
        # keep the whole-product price (new amount), add a 2L price; the 1.5L price is dropped
        "prices": [
            {"id": whole_price["id"], "price": 22, "minimumQuantity": 1},
            {"price": 80, "minimumQuantity": 1, "variantKey": "new-9"},
        ],
    }
    response = client.put(f"/api/v1/businesses/{business_id}/products/{product_id}/full", json=form)
    assert response.status_code == 200, response.text

    result = client.get(f"/api/v1/businesses/{business_id}/products/{product_id}/full").json()
    assert result["product"]["productName"] == "Cola Classic"
    names = {v["variantName"]: v["id"] for v in result["variants"]}
    assert set(names) == {"300ml", "2L"}
    assert names["300ml"] == small["id"]  # same variant, renamed
    assert big["id"] not in names.values()  # removed
    assert sorted((p["price"], p["variantId"]) for p in result["prices"]) == [(22, None), (80, names["2L"])]


def test_a_variant_with_stock_cannot_be_removed(client):
    business_id = create_business(client)["id"]
    saved = client.post(f"/api/v1/businesses/{business_id}/products/full", json=FORM).json()
    product_id = saved["product"]["id"]
    location = client.post(
        f"/api/v1/businesses/{business_id}/locations", json={"locationName": "Store", "locationType": "STORE"}
    ).json()
    client.post(
        f"/api/v1/businesses/{business_id}/inventory",
        json={"productId": product_id, "variantId": saved["variants"][0]["id"], "locationId": location["id"], "quantity": 5},
    )

    form = {"productName": "Cola", "unit": "bottle", "variants": [{"key": saved["variants"][1]["id"], "variantName": "1.5L"}]}
    response = client.put(f"/api/v1/businesses/{business_id}/products/{product_id}/full", json=form)
    assert response.status_code == 400
    assert "still has stock" in response.json()["detail"]


def test_all_prices_in_one_request(client):
    business_id = create_business(client)["id"]
    client.post(f"/api/v1/businesses/{business_id}/products/full", json=FORM)
    prices = client.get(f"/api/v1/businesses/{business_id}/prices").json()
    assert sorted(p["price"] for p in prices) == [20, 65]


def test_price_must_point_to_a_variant_in_the_form():
    bad = {**FORM, "prices": [{"price": 10, "minimumQuantity": 1, "variantKey": "nope"}]}
    with pytest.raises(ValidationError, match="points to a variant that is not in the form"):
        ProductFormIn.model_validate(bad)
