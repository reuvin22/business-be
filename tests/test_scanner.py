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


def start(client, shop, location_id, till, allow_register=False):
    body = {"locationId": location_id, "tillDeviceId": till, "allowRegister": allow_register}
    response = client.post(f"{shop}/scanner-sessions", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def approve(client, shop, started, till):
    response = client.post(f"{shop}/scanner-sessions/{started['session']['id']}/approve", params={"till_device_id": till})
    assert response.status_code == 204, response.text


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
    # Nothing works until each till approves its phone (a photographed QR code is useless)
    waiting = client.post(scans(a), json={"barcode": "4800001"}, headers={"X-Scanner-Token": token_a})
    assert waiting.status_code == 403
    # Another till cannot approve (or end) it
    other = client.post(f"{shop}/scanner-sessions/{a['session']['id']}/approve", params={"till_device_id": TILL_B})
    assert other.status_code == 403
    approve(client, shop, a, TILL_A)
    approve(client, shop, b, TILL_B)

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


def test_register_product_is_offered_only_to_tills_that_may_manage_products(monkeypatch):
    from types import SimpleNamespace

    from app.controllers import scanner_controller
    from app.schemas.enums import Permission

    session = SimpleNamespace(till_uid="u1", till_name="Ana", allow_register=True, approved=True)
    admin = SimpleNamespace(can=lambda permission: permission == Permission.MANAGE_PRODUCTS)
    cashier = SimpleNamespace(can=lambda permission: False)
    monkeypatch.setattr(scanner_controller, "_till_access", lambda db, business_id, s: admin)
    assert scanner_controller._actions(None, "b1", session) == ["register_product"]
    monkeypatch.setattr(scanner_controller, "_till_access", lambda db, business_id, s: cashier)
    assert scanner_controller._actions(None, "b1", session) == []
    monkeypatch.setattr(scanner_controller, "_till_access", lambda db, business_id, s: None)  # left the team
    assert scanner_controller._actions(None, "b1", session) == []


def test_registering_a_product_from_the_phone(client, firestore_db):
    business_id = create_business(client)["id"]
    _, location_id = create_product_with_stock(client, business_id)
    shop = f"/api/v1/businesses/{business_id}/pos"
    plain = start(client, shop, location_id, TILL_B)  # registering not allowed: scanning only
    phone = pair(client, plain["pairingCode"]).json()
    approve(client, shop, plain, TILL_B)
    plain_path = f"/api/v1/pos/scanner/{business_id}/{plain['session']['id']}"
    assert client.get(plain_path, headers={"X-Scanner-Token": phone["token"]}).json()["actions"] == []
    refused = client.post(f"{plain_path}/products", json={"productName": "X", "barcode": "1"}, headers={"X-Scanner-Token": phone["token"]})
    assert refused.status_code == 403

    till = start(client, shop, location_id, TILL_A, allow_register=True)  # the owner is signed in on the till
    paired = pair(client, till["pairingCode"]).json()
    assert paired["actions"] == []  # not before the till approves
    approve(client, shop, till, TILL_A)
    phone = f"/api/v1/pos/scanner/{business_id}/{till['session']['id']}"
    headers = {"X-Scanner-Token": paired["token"]}
    assert client.get(phone, headers=headers).json()["actions"] == ["register_product"]

    assert client.get(f"{phone}/lookup", params={"barcode": "4809999"}, headers=headers).json()["productName"] == ""
    body = {
        "productName": "Bread",
        "barcode": "4809999",
        "unit": "pack",
        "costPrice": 30,
        "description": "Fresh every morning",
        "orderRules": {"minimumOrderQuantity": 2, "orderMultiple": 2},
        "prices": [{"priceType": "RETAIL", "price": 45, "minimumQuantity": 1}],
        "specifications": [{"name": "Weight", "value": "500 g"}],
        "stock": 12,
    }
    saved = client.post(f"{phone}/products", json=body, headers=headers)
    assert saved.status_code == 201, saved.text
    assert client.get(f"{phone}/lookup", params={"barcode": "4809999"}, headers=headers).json()["productName"] == "Bread"
    assert client.post(f"{phone}/products", json=body, headers=headers).status_code == 400  # the barcode is taken

    # It sells at the till right away: the scan finds it
    assert client.post(f"{phone}/scans", json={"barcode": "4809999"}, headers=headers).status_code == 201
    assert client.post(f"{phone}/products", json=body).status_code == 401  # no token, no product


def test_a_phone_connected_from_the_web_app_only_registers_products(client, firestore_db):
    business_id = create_business(client)["id"]
    product_id, location_id = create_product_with_stock(client, business_id)
    client.put(f"/api/v1/businesses/{business_id}/products/{product_id}", json={"productName": "Cola 1.5L", "barcode": "4800001"})
    started = client.post(
        f"/api/v1/businesses/{business_id}/admin-scanner-sessions", json={"locationId": location_id, "tillDeviceId": TILL_A}
    )
    assert started.status_code == 201, started.text
    paired = pair(client, started.json()["pairingCode"]).json()
    assert paired["session"]["mode"] == "admin" and not paired["session"]["approved"]
    session_id = started.json()["session"]["id"]
    response = client.post(f"/api/v1/businesses/{business_id}/admin-scanner-sessions/{session_id}/approve", params={"till_device_id": TILL_A})
    assert response.status_code == 204, response.text

    phone = f"/api/v1/pos/scanner/{business_id}/{started.json()['session']['id']}"
    headers = {"X-Scanner-Token": paired["token"]}
    assert client.post(f"{phone}/scans", json={"barcode": "4800001"}, headers=headers).status_code == 400  # no till cart
    body = {"productName": "Bread", "barcode": "4809999", "prices": [{"priceType": "RETAIL", "price": 45}]}
    assert client.post(f"{phone}/products", json=body, headers=headers).status_code == 201


def test_the_phone_form_takes_what_the_web_form_takes():
    """The phone registers products with the same form as the web app (one schema), plus starting stock."""
    from app.schemas.product import ProductFormIn
    from app.schemas.scanner import PhoneProductIn

    assert set(ProductFormIn.model_fields) <= set(PhoneProductIn.model_fields)
    assert set(PhoneProductIn.model_fields) - set(ProductFormIn.model_fields) == {"stock"}


def test_registering_needs_the_session_to_allow_it_and_an_approved_phone(monkeypatch):
    from types import SimpleNamespace

    from app.controllers import scanner_controller
    from app.schemas.enums import Permission

    admin = SimpleNamespace(can=lambda permission: permission == Permission.MANAGE_PRODUCTS)
    monkeypatch.setattr(scanner_controller, "_till_access", lambda db, business_id, s: admin)
    not_allowed = SimpleNamespace(till_uid="u1", till_name="Ana", allow_register=False, approved=True)
    not_approved = SimpleNamespace(till_uid="u1", till_name="Ana", allow_register=True, approved=False)
    assert scanner_controller._actions(None, "b1", not_allowed) == []  # an admin at the till is not enough
    assert scanner_controller._actions(None, "b1", not_approved) == []  # a photographed QR code gets nothing


def test_only_a_hash_of_the_till_id_is_stored():
    from app.controllers.scanner_controller import _device

    assert TILL_A not in _device(TILL_A) and len(_device(TILL_A)) == 64
    assert _device(TILL_A) != _device(TILL_B)


def test_made_up_tokens_are_limited_per_address():
    from app.core import rate_limit as rl

    rl.reset()
    limit = rl.SCANNERS_PER_ADDRESS
    for _ in range(limit.requests):
        assert rl.hit("ip:9.9.9.9", limit) is None
    assert rl.hit("ip:9.9.9.9", limit) is not None

