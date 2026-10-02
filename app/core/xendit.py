"""Online payments at the counter through Xendit (e-wallets, cards, bank transfer).

We use Xendit Payment Sessions: the API makes a hosted payment page for the exact total, the till shows
it as a QR code, and the customer pays on their phone. Xendit then tells us (webhook), or the till asks
(GET /sessions/{id}), and the sale is completed.

Docs: https://docs.xendit.co/apidocs/create-session.md
The secret key (XENDIT_SECRET_KEY) stays on this server. Never send it to a browser.
"""

import httpx
from fastapi import HTTPException, status

from app.core.config import settings

API_URL = "https://api.xendit.co"

# The Philippine channels offered for each way of paying (codes from the Xendit docs)
CHANNELS = {
    "E_WALLET": ["GCASH", "PAYMAYA", "GRABPAY", "SHOPEEPAY", "QRPH"],
    "CARD": ["CARDS"],
    "BANK_TRANSFER": ["BPI_DIRECT_DEBIT", "UBP_DIRECT_DEBIT"],
}
# Xendit's smallest amount per way of paying, in PHP
MINIMUM_AMOUNT = {"E_WALLET": 1, "CARD": 20, "BANK_TRANSFER": 1}


class XenditError(HTTPException):
    """Xendit refused or could not be reached. The message is safe to show at the till."""

    def __init__(self, message: str):
        super().__init__(status_code=status.HTTP_502_BAD_GATEWAY, detail=message)


def _request(method: str, path: str, body: dict | None = None) -> dict:
    try:
        response = httpx.request(
            method,
            f"{API_URL}{path}",
            json=body,
            auth=(settings.xendit_secret_key.strip(), ""),  # Basic auth: the secret key as the username
            timeout=20,
        )
    except httpx.HTTPError as error:
        raise XenditError(f"Could not reach Xendit ({type(error).__name__}). Please try again.") from error
    data = response.json() if response.content else {}
    if response.status_code >= 400:
        message = data.get("message") or data.get("error_code") or response.reason_phrase
        raise XenditError(f"Xendit: {message}")
    return data


def create_session(
    *, reference_id: str, amount: float, currency: str, method: str, description: str, customer_reference: str
) -> dict:
    """A hosted payment page for this amount. Returns Xendit's session (payment_session_id, payment_link_url, ...)."""
    return _request(
        "POST",
        "/sessions",
        {
            "reference_id": reference_id,
            "session_type": "PAY",
            "mode": "PAYMENT_LINK",
            "amount": amount,
            "currency": currency,
            "country": "PH",
            "allowed_payment_channels": CHANNELS[method],
            "description": description[:1000],
            # A walk-in customer has no account; Xendit still needs someone to attach the payment to
            "customer": {
                "type": "INDIVIDUAL",
                "reference_id": customer_reference,
                "individual_detail": {"given_names": "Walk-in customer"},
            },
        },
    )


def get_session(session_id: str) -> dict:
    """The session as Xendit sees it now. status: ACTIVE, COMPLETED, EXPIRED, or CANCELED."""
    return _request("GET", f"/sessions/{session_id}")


def cancel_session(session_id: str) -> None:
    """Stops the payment page from taking money (best effort: it may already be paid or expired)."""
    try:
        _request("POST", f"/sessions/{session_id}/cancel")
    except XenditError:
        pass
