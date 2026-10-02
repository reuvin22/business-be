"""Online payments at the counter (Xendit). Xendit is replaced by a fake: tests never call it."""

import httpx
import pytest
from fastapi import HTTPException

from app.controllers import pos_controller
from app.core import xendit
from app.core.config import settings
from app.core.firebase import get_db
from app.models.pos import OnlinePayment
from app.schemas.enums import PosPaymentType
from app.schemas.pos import CheckoutIn
from tests.conftest import login_as
from tests.test_pos import TODAY, shop, stock_quantity  # noqa: F401 (shop is a fixture)


def cart(method: str) -> CheckoutIn:
    return CheckoutIn(location_id="l1", items=[{"productId": "p1", "quantity": 1}], payment_method=method, date=TODAY)


def test_card_and_bank_transfer_only_go_through_xendit(monkeypatch):
    monkeypatch.setattr(settings, "xendit_secret_key", "")
    for method in (PosPaymentType.CARD, PosPaymentType.BANK_TRANSFER):
        with pytest.raises(HTTPException) as refused:
            pos_controller.checkout(None, None, cart(method))
        assert refused.value.status_code == 400

    # With Xendit on, an e-wallet is paid online too (no more "the seller checked the phone")
    monkeypatch.setattr(settings, "xendit_secret_key", "xnd_development_test")
    with pytest.raises(HTTPException):
        pos_controller.checkout(None, None, cart(PosPaymentType.E_WALLET))


def test_xendit_errors_are_readable(monkeypatch):
    monkeypatch.setattr(settings, "xendit_secret_key", "xnd_development_test")

    def refuse(method, url, **kwargs):
        return httpx.Response(400, json={"error_code": "API_VALIDATION_ERROR", "message": "amount is too small"})

    monkeypatch.setattr(xendit.httpx, "request", refuse)
    with pytest.raises(xendit.XenditError) as error:
        xendit.get_session("ps-1")
    assert error.value.detail == "Xendit: amount is too small"

    def unreachable(method, url, **kwargs):
        raise httpx.ConnectTimeout("slow")

    monkeypatch.setattr(xendit.httpx, "request", unreachable)
    with pytest.raises(xendit.XenditError) as error:
        xendit.get_session("ps-1")
    assert "Could not reach Xendit" in error.value.detail


def test_the_webhook_needs_the_token(client_without_db, monkeypatch):
    monkeypatch.setattr(settings, "xendit_webhook_token", "secret-token")
    handled = []
    monkeypatch.setattr(pos_controller, "handle_xendit_webhook", lambda db, payload: handled.append(payload))
    url = "/api/v1/webhooks/xendit"
    body = {"event": "payment_session.completed", "data": {"reference_id": "b1_p1"}}

    assert client_without_db.post(url, json=body).status_code == 401
    assert client_without_db.post(url, json=body, headers={"x-callback-token": "wrong"}).status_code == 401
    assert client_without_db.post(url, json=body, headers={"x-callback-token": "secret-token"}).status_code == 200
    assert handled == [body]


def test_paying_online_sells_once(client, shop, monkeypatch):
    """With the Firestore emulator: QR code first, nothing sold; once Xendit says paid, sold exactly once."""
    monkeypatch.setattr(settings, "xendit_secret_key", "xnd_development_test")
    sessions = {}

    def create_session(**request):
        sessions["ps-1"] = "ACTIVE"
        return {"payment_session_id": "ps-1", "payment_link_url": "https://dev.xen.to/abc", "amount": request["amount"]}

    monkeypatch.setattr(xendit, "create_session", create_session)
    monkeypatch.setattr(xendit, "get_session", lambda session_id: {"status": sessions[session_id], "payment_id": "py-1"})

    login_as("seller@test.com")
    base = f"/api/v1/businesses/{shop['business_id']}/pos/payments"
    body = {
        "locationId": shop["location_id"],
        "items": [{"productId": shop["product_id"], "quantity": 3}],
        "paymentMethod": "E_WALLET",
        "date": TODAY,
    }
    started = client.post(base, json=body)
    assert started.status_code == 201, started.text
    payment = started.json()
    assert (payment["status"], payment["paymentLinkUrl"]) == ("PENDING", "https://dev.xen.to/abc")
    assert stock_quantity(client, shop) == 100  # nothing sold yet

    assert client.get(f"{base}/{payment['id']}").json()["status"] == "PENDING"

    sessions["ps-1"] = "COMPLETED"
    paid = client.get(f"{base}/{payment['id']}").json()
    assert paid["status"] == "COMPLETED"
    assert (paid["receipt"]["paymentMethod"], paid["receipt"]["paymentReference"]) == ("E_WALLET", "py-1")
    assert stock_quantity(client, shop) == 97

    # Finishing it again (e.g. the webhook arriving late) does not sell it twice: the receipt id is fixed
    db = client.app.dependency_overrides[get_db]()
    again = OnlinePayment.model_validate({**paid, "status": "PENDING"})
    pos_controller.complete_online_payment(db, shop["business_id"], again, "py-1")
    assert stock_quantity(client, shop) == 97
