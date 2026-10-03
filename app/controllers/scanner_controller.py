"""Phone scanners for the selling app (see app/models/scanner.py).

1. A till starts a session and shows its own one-time pairing code as a QR code (start_session). The till is
   identified by a random id its browser keeps (till_device_id), so every till has its own sessions and codes.
2. The phone scans the QR code (pair). It does not sign in: the code (one use, 10 minutes) proves someone at the
   till showed it. The phone gets a secret token for that session only.
3. Every barcode the phone scans, with its token, is checked against the catalog and saved as a scan (add_scan).
   The till listens to its own session's scans and puts the products in its cart. Nothing is sold here: the
   cashier charges on the till.

What a token allows is deliberately small: adding products to one till's cart, until that session ends (the till
disconnects, starts a new code, or 12 hours pass). It cannot sell, see prices, or read anything else.
"""

import datetime
import hashlib
import hmac
import secrets

from fastapi import HTTPException, status
from google.api_core.exceptions import AlreadyExists
from google.cloud.firestore import Client, FieldFilter

from app.controllers import crud, inventory_controller, product_controller
from app.controllers.crud import bad_request, forbidden, not_found
from app.controllers.pos_controller import _get_location as get_location
from app.controllers.pos_controller import catalog_for
from app.dependencies.business_access import BusinessAccess, load_access, load_business
from app.models.business import Business
from app.models.scanner import (
    Scan,
    ScannerPairing,
    ScannerSecret,
    ScannerSession,
    pairing_document,
    scanner_sessions_collection,
    scans_collection,
    secret_document,
)
from app.schemas.enums import BusinessStatus, Permission, PriceType
from app.schemas.pos import PosProduct
from app.schemas.inventory import InventoryIn
from app.schemas.product import PriceDraft, ProductFormIn
from app.schemas.scanner import (
    REGISTER_PRODUCT,
    BarcodeLookup,
    PairedScanner,
    PhoneProductIn,
    PhoneProductSaved,
    PhoneStatus,
    ScanIn,
    ScannerSessionStarted,
    ScannerSessionView,
)
from app.schemas.user import CurrentUser
from app.utils.helpers import current_time_ms

SESSION_HOURS = 12  # a shift; then the phone pairs again
PAIRING_MINUTES = 10  # the code on the till's screen works this long, and once
# No 0/O or 1/I/L: the code can also be typed on the phone
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
QR_PREFIX = "SIRIS-SCAN:"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_code(db: Client, pairing: ScannerPairing) -> str:
    """Saves the pairing under a code no other till has. create() fails if the code exists, so even two tills
    starting at the same moment can never get the same code."""
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        try:
            pairing_document(db, code).create(pairing.model_copy(update={"id": code}).to_firestore())
            return code
        except AlreadyExists:
            continue  # taken (by another till, or an old code): pick another
    raise RuntimeError("Could not make a unique pairing code")


def _end(db: Client, business_id: str, session_id: str) -> None:
    """Ends a session: its phone's token stops working at once."""
    scanner_sessions_collection(db, business_id).document(session_id).update({"active": False, "updatedAt": current_time_ms()})
    secret_document(db, business_id, session_id).delete()


# ---- The till (signed in to the selling app) -------------------------------------------------------


def start_session(db: Client, access: BusinessAccess, location_id: str, till_device_id: str) -> ScannerSessionStarted:
    """A new session (and QR code) for THIS till. Ends this till's earlier sessions, never another till's."""
    access.require(Permission.USE_POS)
    location = get_location(db, access, location_id)  # the same check as selling: a seller only at their store
    this_till = FieldFilter("tillDeviceId", "==", till_device_id)
    for snapshot in scanner_sessions_collection(db, access.business_id).where(filter=this_till).stream():
        if (snapshot.to_dict() or {}).get("active"):
            _end(db, access.business_id, snapshot.id)

    now = current_time_ms()
    ref = scanner_sessions_collection(db, access.business_id).document()  # a random id: unique per session
    session = ScannerSession(
        id=ref.id,
        location_id=location.id,
        location_name=location.location_name,
        till_device_id=till_device_id,
        till_uid=access.user.uid,
        till_name=access.member.display_name or access.user.name or access.user.email or "",
        expires_at=now + SESSION_HOURS * 3600 * 1000,
        created_at=now,
        updated_at=now,
    )
    ref.set(session.to_firestore())
    pairing = ScannerPairing(
        business_id=access.business_id, session_id=ref.id, expires_at=now + PAIRING_MINUTES * 60 * 1000, created_at=now
    )
    code = _new_code(db, pairing)
    return ScannerSessionStarted(
        session=session, pairing_code=code, qr_text=f"{QR_PREFIX}{code}", pairing_expires_at=pairing.expires_at
    )


def end_session(db: Client, access: BusinessAccess, session_id: str, till_device_id: str) -> None:
    """The till disconnects its phone. Only that till (or a manager) may."""
    session = crud.read_fresh(scanner_sessions_collection(db, access.business_id).document(session_id), ScannerSession)
    if session is None:
        raise not_found("Scanner session")
    if session.till_device_id != till_device_id and not access.can(Permission.MANAGE_INVENTORY):
        raise forbidden("This phone is connected to another till")
    _end(db, access.business_id, session_id)


# ---- The phone (no sign-in: the QR code, then its token) ---------------------------------------------


def pair(db: Client, code: str, scanner_name: str) -> PairedScanner:
    """The phone joins the session whose code the till shows. Works once, within PAIRING_MINUTES."""
    # The QR code holds "SIRIS-SCAN:<code>"; a typed code may have a dash ("ABCD-2345") or spaces
    code = code.strip().upper().removeprefix(QR_PREFIX).replace("-", "").replace(" ", "")
    if len(code) != CODE_LENGTH or any(c not in CODE_ALPHABET for c in code):
        raise not_found("Pairing code")
    ref = pairing_document(db, code)
    pairing = crud.read_fresh(ref, ScannerPairing)
    if pairing is None or pairing.expires_at < current_time_ms():
        raise not_found("Pairing code (it may have expired: tap New code on the till)")
    ref.delete()  # one use, even if the rest fails

    session_ref = scanner_sessions_collection(db, pairing.business_id).document(pairing.session_id)
    session = crud.read_fresh(session_ref, ScannerSession)
    business = load_business(db, pairing.business_id)
    if session is None or not session.active or business is None:
        raise not_found("Scanner session (start again on the till)")

    token = secrets.token_urlsafe(32)
    now = current_time_ms()
    secret = ScannerSecret(business_id=business.id, session_id=session.id, token_hash=_hash(token), created_at=now)
    secret_document(db, business.id, session.id).set(secret.to_firestore())
    session.scanner_name = scanner_name.strip()[:40] or "Phone scanner"
    session.paired_at = now
    session.updated_at = now
    session_ref.set(session.to_firestore())
    return PairedScanner(
        business_id=business.id,
        business_name=business.business_name,
        session=ScannerSessionView.model_validate(session),
        token=token,
        actions=_actions(db, business.id, session),
    )


def _not_paired(message: str = "This phone is not connected to that till. Scan the till's QR code again.") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=message)


def phone_session(db: Client, business_id: str, session_id: str, token: str) -> tuple[Business, ScannerSession]:
    """The session this phone's token opens, or 401 (the phone must scan the till's QR code again)."""
    secret = crud.read_fresh(secret_document(db, business_id, session_id), ScannerSecret) if token else None
    if secret is None or not hmac.compare_digest(secret.token_hash, _hash(token)):
        raise _not_paired()
    session = crud.read_fresh(scanner_sessions_collection(db, business_id).document(session_id), ScannerSession)
    business = load_business(db, business_id)
    if session is None or business is None or business.business_status != BusinessStatus.ACTIVE:
        raise _not_paired()
    if not session.active or session.expires_at < current_time_ms():
        raise _not_paired("This connection has ended. Scan the till's QR code again.")
    return business, session


# ---- More than scanning: what the person at the till may also do from the phone ----------------------


def _till_access(db: Client, business_id: str, session: ScannerSession) -> BusinessAccess | None:
    """The person signed in on the till that connected the phone, as they are NOW (None if they left the team)."""
    try:
        return load_access(db, business_id, CurrentUser(uid=session.till_uid, name=session.till_name))
    except HTTPException:
        return None


def _actions(db: Client, business_id: str, session: ScannerSession) -> list[str]:
    access = _till_access(db, business_id, session)
    return [REGISTER_PRODUCT] if access is not None and access.can(Permission.MANAGE_PRODUCTS) else []


def phone_status(db: Client, business_id: str, session_id: str, token: str) -> PhoneStatus:
    _, session = phone_session(db, business_id, session_id, token)
    return PhoneStatus(session=ScannerSessionView.model_validate(session), actions=_actions(db, business_id, session))


def lookup_barcode(db: Client, business_id: str, session_id: str, token: str, barcode: str) -> BarcodeLookup:
    """Before registering: is this barcode already one of the business's products?"""
    business, _ = phone_session(db, business_id, session_id, token)
    found = _find_item(catalog_for(db, business, datetime.datetime.now(datetime.UTC).date()), barcode.strip())
    return BarcodeLookup(barcode=barcode.strip(), product_name=found[1] if found else "")


def register_product(db: Client, business_id: str, session_id: str, token: str, product_in: PhoneProductIn) -> PhoneProductSaved:
    """Registers a new product from the phone, in the name of the person signed in on the till (who must be
    allowed to manage products, e.g. the owner or an admin): its barcode, selling price, and starting stock."""
    business, session = phone_session(db, business_id, session_id, token)
    access = _till_access(db, business_id, session)
    if access is None or not access.can(Permission.MANAGE_PRODUCTS):
        raise forbidden("The person signed in on the till may not add products")

    barcode = product_in.barcode.strip()
    today = datetime.datetime.now(datetime.UTC).date()
    taken = _find_item(catalog_for(db, business, today), barcode)
    if taken is not None:
        raise bad_request(f"This barcode is already used by {taken[1]}")

    form = ProductFormIn(
        product_name=product_in.product_name,
        barcode=barcode,
        unit=product_in.unit,
        cost_price=product_in.cost_price,
        prices=[PriceDraft(price_type=PriceType.RETAIL, price=product_in.price, currency=business.currency, minimum_quantity=1)],
    )
    saved = product_controller.save_product_full(db, access, form)
    if product_in.stock > 0:
        stock = InventoryIn(product_id=saved.product.id, location_id=session.location_id, quantity=product_in.stock)
        inventory_controller.add_stock_record(db, access, stock, note="Registered with the phone scanner")
    return PhoneProductSaved(product_id=saved.product.id, product_name=saved.product.product_name)


def phone_disconnect(db: Client, business_id: str, session_id: str, token: str) -> None:
    phone_session(db, business_id, session_id, token)
    _end(db, business_id, session_id)


def _find_item(catalog: list[PosProduct], barcode: str) -> tuple[str, str] | None:
    """(item key, name) of the product with this barcode (or SKU), the same way the till finds it.
    A variant's own code wins over its product's."""
    for product in catalog:
        for variant in product.variants:
            if barcode in (variant.barcode, variant.sku):
                return f"{product.id}__{variant.id}", f"{product.product_name} ({variant.variant_name})"
    for product in catalog:
        if barcode in (product.barcode, product.sku):
            if not product.variants:
                return f"{product.id}__base", product.product_name
            first = product.variants[0]
            return f"{product.id}__{first.id}", f"{product.product_name} ({first.variant_name})"
    return None


def add_scan(db: Client, business_id: str, session_id: str, token: str, scan_in: ScanIn, today: datetime.date) -> Scan:
    """One scanned barcode. It is only put in the till's cart, never sold here."""
    if abs((today - datetime.datetime.now(datetime.UTC).date()).days) > 1:
        raise bad_request("Check the date on this phone")
    business, session = phone_session(db, business_id, session_id, token)
    barcode = scan_in.barcode.strip()
    found = _find_item(catalog_for(db, business, today), barcode)
    if found is None:
        raise not_found(f"Product with barcode {barcode}")
    item_key, name = found

    now = current_time_ms()
    ref = scans_collection(db, business_id, session_id).document()
    scan = Scan(
        id=ref.id,
        barcode=barcode,
        item_key=item_key,
        product_name=name,
        scanned_by_name=session.scanner_name,
        created_at=now,
        updated_at=now,
    )
    ref.set(scan.to_firestore())
    scanner_sessions_collection(db, business_id).document(session_id).update({"lastScanAt": now})
    return scan
