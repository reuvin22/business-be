"""The phone scanner app (business-scanner) and the till it is paired with. See app/models/scanner.py."""

from pydantic import Field

from app.models.scanner import ScannerSession
from app.schemas.base import CamelModel


class ScannerSessionStartIn(CamelModel):
    location_id: str = Field(min_length=1)  # the store the till sells at
    # A random id this till's browser keeps: each till has its own sessions (two tills never share one)
    till_device_id: str = Field(min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class ScannerSessionStarted(CamelModel):
    """What the till shows: its own one-time pairing code, as a QR code (qr_text) and as text."""

    session: ScannerSession
    pairing_code: str
    qr_text: str  # "SIRIS-SCAN:<code>"
    pairing_expires_at: int


class ScannerSessionView(CamelModel):
    id: str
    location_id: str
    location_name: str
    till_name: str
    scanner_name: str
    active: bool
    expires_at: int
    paired_at: int | None = None


class PairIn(CamelModel):
    code: str = Field(min_length=4, max_length=40)  # from the QR code ("SIRIS-SCAN:<code>") or typed
    scanner_name: str = Field(default="", max_length=40)  # what the till shows, e.g. "Ana's phone"


class PairedScanner(CamelModel):
    """The phone is connected. It keeps `token` (secret) and sends it with every scan; nothing else is needed."""

    business_id: str
    business_name: str
    session: ScannerSessionView
    token: str


class ScanIn(CamelModel):
    barcode: str = Field(min_length=1, max_length=64)
