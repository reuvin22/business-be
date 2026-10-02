from google.cloud.firestore import Client, CollectionReference

from app.models.base import FirestoreModel
from app.models.business import business_subcollection
from app.schemas.base import CamelModel
from app.schemas.enums import OnlinePaymentStatus, PosPaymentType, ReceiptStatus
from app.schemas.pos import CheckoutIn

# Firestore location:  businesses/{businessId}/receipts/{receiptId}
#
# One receipt per checkout in the selling app. Each line is also saved as a Sale
# (businesses/{businessId}/sales), so the main app's sales and dashboard include it.


class ReceiptLine(CamelModel):
    product_id: str
    variant_id: str | None = None
    product_name: str
    variant_name: str = ""
    unit: str = ""
    quantity: int
    unit_price: float
    line_total: float
    sale_id: str  # the Sale saved for this line


class Receipt(FirestoreModel):
    receipt_number: str  # short and readable, e.g. 20260928-K3F9QX
    date: str  # YYYY-MM-DD, the seller's local date
    location_id: str
    location_name: str = ""
    items: list[ReceiptLine]
    total: float
    amount_paid: float
    change_given: float  # amount_paid - total
    payment_method: PosPaymentType
    note: str = ""
    status: ReceiptStatus = ReceiptStatus.COMPLETED
    seller_uid: str
    seller_name: str = ""
    voided_at: int | None = None
    voided_by_name: str = ""
    void_reason: str = ""
    payment_reference: str = ""  # online payments: Xendit's payment id


def receipts_collection(db: Client, business_id: str) -> CollectionReference:
    return business_subcollection(db, business_id, "receipts")


# Firestore location:  businesses/{businessId}/onlinePayments/{paymentId}
#
# A cart being paid online (Xendit). When the payment arrives, the cart is checked out and the
# receipt gets the SAME id as this payment, so it can never be saved twice (webhook + till both asking).


class OnlinePayment(FirestoreModel):
    checkout: CheckoutIn  # the cart, saved as it was when the seller pressed Charge
    payment_method: PosPaymentType
    total: float
    currency: str
    status: OnlinePaymentStatus = OnlinePaymentStatus.PENDING
    session_id: str = ""  # Xendit payment session (ps-...)
    payment_link_url: str = ""  # the page the customer pays on (shown as a QR code)
    payment_reference: str = ""  # Xendit's payment id, once paid
    receipt_id: str = ""
    error: str = ""  # why a paid sale could not be saved
    seller_uid: str
    seller_name: str = ""


def online_payments_collection(db: Client, business_id: str) -> CollectionReference:
    return business_subcollection(db, business_id, "onlinePayments")


class OnlinePaymentView(OnlinePayment):
    """An online payment, with its receipt once the sale is saved."""

    receipt: Receipt | None = None

