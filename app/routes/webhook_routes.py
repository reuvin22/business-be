"""Messages from other services (no login: each one proves itself another way)."""

import hmac

from fastapi import APIRouter, Body, Depends, Header, HTTPException, status
from google.cloud.firestore import Client

from app.controllers import pos_controller
from app.core.config import settings
from app.core.firebase import get_db

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/xendit")
def xendit_webhook(
    payload: dict = Body(...), x_callback_token: str = Header(default=""), db: Client = Depends(get_db)
):
    """Set this URL in the Xendit Dashboard (Settings > Developers > Webhooks) for Payment Sessions.
    Xendit proves it sent the message with the verification token (XENDIT_WEBHOOK_TOKEN).

    A normal (not async) function: it waits on Xendit and Firestore, so FastAPI runs it in a worker thread.
    Any error answers 500, and Xendit tries again later."""
    expected = settings.xendit_webhook_token.strip()
    if not expected or not hmac.compare_digest(x_callback_token.encode(), expected.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid callback token")
    pos_controller.handle_xendit_webhook(db, payload)
    return {"received": True}
