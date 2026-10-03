"""The phone scanner (business-scanner app): a till's own QR code, a phone with no login, scans into that till's cart."""

from app.controllers.scanner_controller import CODE_ALPHABET, _find_item
from app.core import rate_limit
from app.schemas.pos import PosProduct, PosVariant
from tests.conftest import create_business, create_product_with_stock, login_as

CATALOG = [
    PosProduct(id="p1", product_name="Cola 1.5L", barcode="4800001", sku="COLA15"),
    PosProduct(
        id="p2",
        product_name="T-shirt",
        barcode="4800002",
        variants=[PosVariant(id="v1", variant_name="Small", barcode="4800002S"), PosVariant(id="v2", variant_name="Large", sku="TS-L")],
    ),
]

TILL_A = "till-a-0000000000000001"
TILL_B = "till-b-0000000000000002"


def test_a_barcode_finds_the_item_like_the_till_does():
    assert _find_item(CATALOG, "4800001") == ("p1__base", "Cola 1.5L")
    assert _find_item(CATALOG, "COLA15") == ("p1__base", "Cola 1.5L")  # the SKU works too
    assert _find_item(CATALOG, "TS-L") == ("p2__v2", "T-shirt (Large)")  # a variant's own code wins
    assert _find_item(CATALOG, "4800002") == ("p2__v1", "T-shirt (Small)")  # the product's code: its first variant
    assert _find_item(CATALOG, "nope") is None


def test_pairing_codes_can_be_typed():
    assert not set("01OIL") & set(CODE_ALPHABET)  # no characters that look alike


def test_pairing_is_limited_per_address():
    rate_limit.reset()
    limits = rate_limit.limits_for("POST", "/api/v1/pos/scanner/pair", signed_in=False)
    assert rate_limit.PAIRING in limits
    assert rate_limit.limits_for("POST", "/api/v1/pos/scanner/b1/s1/scans", signed_in=False, scanner=True) == [rate_limit.SCANNER]
    assert rate_limit.caller_key("", "1.2.3.4", "token-a") != rate_limit.caller_key("", "1.2.3.4", "token-b")


def start(client, shop, location_id, till):
    response = client.post(f"{shop}/scanner-sessions", json={"locationId": location_id, "tillDeviceId": till})
    assert response.status_code == 201, response.text
    return response.json()


def pair(client, code, name="Phone"):
    login_as("owner@test.com")
    from app.dependencies.auth import get_current_user
    from app.main import app

    app.dependency_overrides.pop(get_current_user, None)  # the phone is not signed in
    response = client.post("/api/v1/pos/scanner/pair", json={"code": code, "scannerName": name})
    login_as("owner@test.com")
    return response


def test_each_till_gets_only_its_own_scans(client, firestore_db):
    business_id = create_business(client)["id"]
    product_id, location_id = create_product_with_stock(client, business_id)
    client.put(f"/api/v1/businesses/{business_id}/products/{product_id}", json={"productName": "Cola 1.5L", "barcode": "4800001"})
    shop = f"/api/v1/businesses/{business_id}/pos"

    # Two tills at the same store, signed in with the same account: each has its own session and code
    a, b = start(client, shop, location_id, TILL_A), start(client, shop, location_id, TILL_B)
    assert a["session"]["id"] != b["session"]["id"]
    assert a["pairingCode"] != b["pairingCode"]
    assert a["qrText"] == f"SIRIS-SCAN:{a['pairingCode']}"

    phone_a = pair(client, a["qrText"], "Ana's phone")
    assert phone_a.status_code == 200, phone_a.text
    token_a = phone_a.json()["token"]
    assert pair(client, a["pairingCode"]).status_code == 404  # a code works once
    token_b = pair(client, b["pairingCode"]).json()["token"]

    scans = lambda session: f"/api/v1/pos/scanner/{business_id}/{session['session']['id']}/scans"  # noqa: E731
    # Each phone can only add to its own till
    assert client.post(scans(a), json={"barcode": "4800001"}, headers={"X-Scanner-Token": token_a}).status_code == 201
    assert client.post(scans(b), json={"barcode": "4800001"}, headers={"X-Scanner-Token": token_a}).status_code == 401
    assert client.post(scans(a), json={"barcode": "4800001"}).status_code == 401  # no token
    assert client.post(scans(b), json={"barcode": "4800001"}, headers={"X-Scanner-Token": token_b}).status_code == 201

    a_scans = firestore_db.collection(f"businesses/{business_id}/scannerSessions/{a['session']['id']}/scans").get()
    assert [s.to_dict()["itemKey"] for s in a_scans] == [f"{product_id}__base"]

    # Nothing was sold: only the till's checkout sells
    assert client.get(f"{shop}/receipts").json() == []

    # A new code on till A ends A's old connection, and never touches till B's
    start(client, shop, location_id, TILL_A)
    assert client.post(scans(a), json={"barcode": "4800001"}, headers={"X-Scanner-Token": token_a}).status_code == 401
    assert client.post(scans(b), json={"barcode": "4800001"}, headers={"X-Scanner-Token": token_b}).status_code == 201

    # Till B disconnects: its phone stops at once
    assert client.delete(f"{shop}/scanner-sessions/{b['session']['id']}", params={"till_device_id": TILL_B}).status_code == 204
    assert client.post(scans(b), json={"barcode": "4800001"}, headers={"X-Scanner-Token": token_b}).status_code == 401
