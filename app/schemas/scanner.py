"""The phone scanner app (business-scanner) and the till it is paired with. See app/models/scanner.py."""

from typing import Literal

from pydantic import Field

from app.models.scanner import ScannerSession
from app.schemas.base import CamelModel
from app.schemas.product import ProductFormIn


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


class PhoneProductIn(ProductFormIn):
    """A new product, registered on the phone after scanning its barcode: the same form as the web app's
    Add product (details, order rules, price tiers, variants, photos, specifications), plus its starting stock."""

    stock: float = Field(default=0, ge=0)  # starting stock at the session's store (for a product without variants)


class Choice(CamelModel):
    value: str
    label: str


class PhoneProductOptions(CamelModel):
    """The business's own choices for the phone's product form (the fixed lists are in the app)."""

    categories: list[Choice]
    brands: list[Choice]
    currency: str


class PhoneProductSaved(CamelModel):
    product_id: str
    product_name: str


class BarcodeLookup(CamelModel):
    """Is this barcode already a product? (Checked before registering a new one.)"""

    barcode: str
    product_name: str = ""  # "" = not registered yet


class ScanIn(CamelModel):
    barcode: str = Field(min_length=1, max_length=64)
