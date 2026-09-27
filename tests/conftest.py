import os

import httpx
import pytest
from fastapi.testclient import TestClient
from google.cloud import firestore

from app.core.firebase import get_db
from app.dependencies.auth import get_current_user
from app.main import app
from app.schemas.user import CurrentUser

# Tests never touch the real database. They use the Firestore emulator (see README),
# which is found through this environment variable, e.g. FIRESTORE_EMULATOR_HOST=127.0.0.1:8080
EMULATOR_HOST = os.environ.get("FIRESTORE_EMULATOR_HOST")
TEST_PROJECT = "demo-my-business"

# Fake accounts used by the tests (instead of real Firebase users)
ACCOUNTS = {
    "owner@test.com": "owner-uid",
    "buyer@test.com": "buyer-uid",
    "staff@test.com": "staff-uid",
    "admin@test.com": "admin-uid",
}


def login_as(email: str, is_admin: bool = False) -> None:
    """Pretend this user is logged in, so tests don't need a real Firebase token."""
    user = CurrentUser(uid=ACCOUNTS[email], email=email, name=email.split("@")[0], is_admin=is_admin)
    app.dependency_overrides[get_current_user] = lambda: user


def fake_find_user_by_email(email: str) -> dict | None:
    uid = ACCOUNTS.get(email)
    return {"uid": uid, "email": email, "display_name": email.split("@")[0]} if uid else None


@pytest.fixture
def client(monkeypatch):
    """A test client connected to the Firestore emulator. Skips the test when the emulator is not running."""
    if not EMULATOR_HOST:
        pytest.skip("Firestore emulator not running (set FIRESTORE_EMULATOR_HOST)")

    # With FIRESTORE_EMULATOR_HOST set, this client talks to the emulator instead of the real Firestore
    test_db = firestore.Client(project=TEST_PROJECT)
    app.dependency_overrides[get_db] = lambda: test_db
    monkeypatch.setattr("app.controllers.member_controller.find_user_by_email", fake_find_user_by_email)
    login_as("owner@test.com")

    yield TestClient(app)

    app.dependency_overrides.clear()
    httpx.delete(f"http://{EMULATOR_HOST}/emulator/v1/projects/{TEST_PROJECT}/databases/(default)/documents")


@pytest.fixture
def client_without_db():
    """A test client for checks that fail before the database is used (like invalid input)."""
    app.dependency_overrides[get_db] = lambda: None
    login_as("owner@test.com")

    yield TestClient(app)

    app.dependency_overrides.clear()


# ---- Helpers that build test data through the API -------------------------------------


def create_business(client, name="Acme Supplies", types=("SUPPLIER",), **extra) -> dict:
    response = client.post(
        "/api/v1/businesses", json={"businessName": name, "businessTypes": list(types), "currency": "PHP", **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_product_with_stock(client, business_id: str, stock: float = 100) -> tuple[str, str]:
    """A public product with price tiers, a warehouse, and stock there. Returns (product_id, location_id)."""
    product = client.post(
        f"/api/v1/businesses/{business_id}/products",
        json={"productName": "Cola 1.5L", "unit": "box", "orderRules": {"minimumOrderQuantity": 10, "orderMultiple": 5}},
    ).json()
    for tier in ({"minimumQuantity": 1, "maximumQuantity": 49, "price": 120}, {"minimumQuantity": 50, "price": 100}):
        response = client.post(f"/api/v1/businesses/{business_id}/products/{product['id']}/prices", json=tier)
        assert response.status_code == 201, response.text

    location = client.post(
        f"/api/v1/businesses/{business_id}/locations",
        json={"locationName": "Main warehouse", "locationType": "WAREHOUSE", "city": "Pasig"},
    ).json()
    response = client.post(
        f"/api/v1/businesses/{business_id}/inventory",
        json={"productId": product["id"], "locationId": location["id"], "quantity": stock, "reorderLevel": 20},
    )
    assert response.status_code == 201, response.text
    client.put(f"/api/v1/businesses/{business_id}/delivery", json={"pickupAvailable": True})
    return product["id"], location["id"]
