"""The phone scanner app (business-scanner) and the till it is paired with. See app/models/scanner.py."""

from typing import Literal

from pydantic import Field

from app.models.scanner import ScannerSession
from app.schemas.base import CamelModel


class ScannerSessionStartIn(CamelModel):
    location_id: str = Field(min_length=1)  # the store the till sells at (admin: where new products' stock goes)
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
    mode: Literal["till", "admin"] = "till"  # admin: the phone only registers products
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


# What else the phone may do, besides putting products in the till's cart. Only offered when the person signed in
# on the till may do it (e.g. an owner or admin with the products.manage permission).
REGISTER_PRODUCT = "register_product"


class PairedScanner(CamelModel):
    """The phone is connected. It keeps `token` (secret) and sends it with every scan; nothing else is needed."""

    business_id: str
    business_name: str
    session: ScannerSessionView
    token: str
    actions: list[str] = []  # e.g. ["register_product"]


class PhoneStatus(CamelModel):
    """The phone checks its connection: still open, and what it may do now (permissions can change)."""

    session: ScannerSessionView
    actions: list[str] = []


class PhoneProductIn(CamelModel):
    """A new product, registered on the phone after scanning its barcode."""

    product_name: str = Field(min_length=1, max_length=200)
    barcode: str = Field(min_length=1, max_length=64)
    unit: str = Field(default="pcs", min_length=1, max_length=20)
    price: float = Field(ge=0)  # the selling price for one (a retail price tier)
    cost_price: float | None = Field(default=None, ge=0)
    stock: float = Field(default=0, ge=0)  # starting stock at the till's store


class PhoneProductSaved(CamelModel):
    product_id: str
    product_name: str


class BarcodeLookup(CamelModel):
    """Is this barcode already a product? (Checked before registering a new one.)"""

    barcode: str
    product_name: str = ""  # "" = not registered yet


class ScanIn(CamelModel):
    barcode: str = Field(min_length=1, max_length=64)
