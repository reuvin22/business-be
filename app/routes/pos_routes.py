"""The selling app (my-business-pos), and the seller accounts the main app manages."""

import datetime

from fastapi import APIRouter, Depends, Header, status
from google.cloud.firestore import Client

from app.controllers import pos_controller, scanner_controller, seller_controller, settings_controller
from app.core.firebase import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.business_access import BusinessAccess, get_business_access, get_pos_access
from app.models.inventory import InventoryItem, StockMovement
from app.models.member import Member
from app.schemas.views import SellerAdded
from app.models.pos import OnlinePaymentView, Receipt
from app.models.scanner import Scan
from app.models.settings import PosSettings
from app.schemas.pos import (
    CheckoutIn,
    PosBusiness,
    PosContext,
    PosProduct,
    PosSettingsIn,
    SellerCreateIn,
    SellerPasswordIn,
    SellerUpdateIn,
    StockChangeIn,
    VoidIn,
)
from app.schemas.scanner import PairedScanner, PairIn, ScanIn, ScannerSessionStarted, ScannerSessionStartIn, ScannerSessionView
from app.schemas.user import CurrentUser

router = APIRouter(tags=["Selling app"])

# ---- Seller accounts (used by the main app's Team page) -------------------------------------


@router.get("/businesses/{business_id}/pos-settings", response_model=PosSettings)
def get_pos_settings(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    """The selling app's template (Default, Grocery, Restaurant, Coffee shop)."""
    return settings_controller.get_pos_settings(db, access.business_id)


@router.put("/businesses/{business_id}/pos-settings", response_model=PosSettings)
def save_pos_settings(
    settings_in: PosSettingsIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return settings_controller.save_pos_settings(db, access, settings_in)


@router.get("/businesses/{business_id}/sellers", response_model=list[Member])
def list_sellers(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return seller_controller.list_sellers(db, access)


@router.post("/businesses/{business_id}/sellers", response_model=SellerAdded, status_code=status.HTTP_201_CREATED)
def create_seller(
    seller_in: SellerCreateIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return seller_controller.create_seller(db, access, seller_in)


@router.put("/businesses/{business_id}/sellers/{user_id}", response_model=Member)
def update_seller(
    user_id: str,
    seller_in: SellerUpdateIn,
    db: Client = Depends(get_db),
    access: BusinessAccess = Depends(get_business_access),
):
    return seller_controller.update_seller(db, access, user_id, seller_in)


@router.put("/businesses/{business_id}/sellers/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def set_seller_password(
    user_id: str,
    password_in: SellerPasswordIn,
    db: Client = Depends(get_db),
    access: BusinessAccess = Depends(get_business_access),
):
    seller_controller.set_password(db, access, user_id, password_in)


@router.delete("/businesses/{business_id}/sellers/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_seller(user_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    seller_controller.remove_seller(db, access, user_id)


# ---- The selling app ------------------------------------------------------------------------


@router.get("/pos/businesses", response_model=list[PosBusiness])
def list_pos_businesses(db: Client = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Businesses the logged-in user can sell for."""
    return pos_controller.list_pos_businesses(db, user)


@router.get("/businesses/{business_id}/pos/context", response_model=PosContext)
def get_context(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_pos_access)):
    return pos_controller.get_context(db, access)


@router.get("/businesses/{business_id}/pos/catalog", response_model=list[PosProduct])
def get_catalog(
    date: datetime.date | None = None, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_pos_access)
):
    """Products for sale with today's prices. Send ?date= (the seller's local date) for date-limited prices."""
    return pos_controller.get_catalog(db, access, date or datetime.date.today())


@router.get("/businesses/{business_id}/pos/stock", response_model=list[InventoryItem])
def list_stock(location_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_pos_access)):
    return pos_controller.list_stock(db, access, location_id)


@router.get("/businesses/{business_id}/pos/stock-history", response_model=list[StockMovement])
def list_stock_history(
    location_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_pos_access)
):
    return pos_controller.list_stock_history(db, access, location_id)


@router.post("/businesses/{business_id}/pos/stock-changes", response_model=InventoryItem)
def change_stock(
    change_in: StockChangeIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_pos_access)
):
    return pos_controller.change_stock(db, access, change_in)


@router.post("/businesses/{business_id}/pos/checkouts", response_model=Receipt, status_code=status.HTTP_201_CREATED)
def checkout(checkout_in: CheckoutIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_pos_access)):
    return pos_controller.checkout(db, access, checkout_in)


@router.get("/businesses/{business_id}/pos/receipts", response_model=list[Receipt])
def list_receipts(
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    date: datetime.date | None = None,
    location_id: str | None = None,
    db: Client = Depends(get_db),
    access: BusinessAccess = Depends(get_pos_access),
):
    """Receipts from date_from to date_to (YYYY-MM-DD, both included). Without dates: the newest of all days.
    date: one day (the same as date_from = date_to; kept for older versions of the app)."""
    if date:
        date_from = date_to = date
    return pos_controller.list_receipts(db, access, date_from, date_to, location_id)


@router.post("/businesses/{business_id}/pos/receipts/{receipt_id}/void", response_model=Receipt)
def void_receipt(
    receipt_id: str, void_in: VoidIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_pos_access)
):
    return pos_controller.void_receipt(db, access, receipt_id, void_in)


@router.delete("/businesses/{business_id}/pos/receipts/{receipt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_receipt(receipt_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_pos_access)):
    """Managers only: removes the receipt and its sales for good (stock goes back unless it was voided)."""
    pos_controller.delete_receipt(db, access, receipt_id)


# ---- Online payments (Xendit) ----------------------------------------------------------------


@router.post(
    "/businesses/{business_id}/pos/payments", response_model=OnlinePaymentView, status_code=status.HTTP_201_CREATED
)
def start_online_payment(
    checkout_in: CheckoutIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_pos_access)
):
    """E-wallet, card, or bank transfer: makes a Xendit payment page for the cart (show it as a QR code).
    The sale is saved when the customer has paid."""
    return pos_controller.start_online_payment(db, access, checkout_in)


@router.get("/businesses/{business_id}/pos/payments/{payment_id}", response_model=OnlinePaymentView)
def get_online_payment(payment_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_pos_access)):
    """Ask every few seconds while the QR code is shown: once paid, the receipt comes with it."""
    return pos_controller.get_online_payment(db, access, payment_id)


@router.post("/businesses/{business_id}/pos/payments/{payment_id}/cancel", response_model=OnlinePaymentView)
def cancel_online_payment(
    payment_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_pos_access)
):
    return pos_controller.cancel_online_payment(db, access, payment_id)


# ---- Phone scanners (the business-scanner app) --------------------------------------------------
# The till is signed in. The phone is NOT: it scans the till's QR code once (pair) and then sends the secret token
# it got in the X-Scanner-Token header. The token only adds products to that one till's cart.


@router.post("/businesses/{business_id}/pos/scanner-sessions", response_model=ScannerSessionStarted, status_code=status.HTTP_201_CREATED)
def start_scanner_session(
    session_in: ScannerSessionStartIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_pos_access)
):
    """The till starts a session and shows its own one-time pairing code (a QR code) for the phone to scan."""
    return scanner_controller.start_session(db, access, session_in.location_id, session_in.till_device_id)


@router.delete("/businesses/{business_id}/pos/scanner-sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def end_scanner_session(
    session_id: str, till_device_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_pos_access)
):
    """The till disconnects its phone (send its till_device_id)."""
    scanner_controller.end_session(db, access, session_id, till_device_id)


@router.post("/pos/scanner/pair", response_model=PairedScanner)
def pair_scanner(pair_in: PairIn, db: Client = Depends(get_db)):
    """The phone scanned the till's QR code (or typed its code). No sign-in: the one-time code is the proof.
    Returns the token the phone sends with every scan."""
    return scanner_controller.pair(db, pair_in.code, pair_in.scanner_name)


@router.get("/pos/scanner/{business_id}/{session_id}", response_model=ScannerSessionView)
def phone_session(business_id: str, session_id: str, x_scanner_token: str = Header(default=""), db: Client = Depends(get_db)):
    """Is the phone still connected? 401 when not (it scans the till's QR code again)."""
    return scanner_controller.phone_session(db, business_id, session_id, x_scanner_token)[1]


@router.delete("/pos/scanner/{business_id}/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def phone_disconnect(business_id: str, session_id: str, x_scanner_token: str = Header(default=""), db: Client = Depends(get_db)):
    scanner_controller.phone_disconnect(db, business_id, session_id, x_scanner_token)


@router.post("/pos/scanner/{business_id}/{session_id}/scans", response_model=Scan, status_code=status.HTTP_201_CREATED)
def add_scan(
    business_id: str,
    session_id: str,
    scan_in: ScanIn,
    date: datetime.date | None = None,
    x_scanner_token: str = Header(default=""),
    db: Client = Depends(get_db),
):
    """The phone scanned a barcode: it appears in its till's cart (not sold until the cashier charges).
    Send ?date= (the phone's local date) so date-limited prices match the till."""
    return scanner_controller.add_scan(db, business_id, session_id, x_scanner_token, scan_in, date or datetime.date.today())
