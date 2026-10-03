"""Phone scanners connected to a till of the selling app (the SIRIS Scanner mobile app, business-scanner).

The phone does not sign in. The till (signed in) shows a QR code; the phone scans it and gets a secret token that
lets it do ONE thing: put products in THAT till's cart. Every till has its own session, its own one-time code, and
its own token, so two tills (even at the same store, with the same account) never get each other's scans.

Firestore locations:
  businesses/{businessId}/scannerSessions/{sessionId}                one till <-> one phone (the till listens to it)
  businesses/{businessId}/scannerSessions/{sessionId}/scans/{scanId} each barcode the phone scanned
  scannerPairings/{code}                                             the one-time code the till shows (QR); private
  scannerSecrets/{businessId}_{sessionId}                            the phone's token (as a hash); private
"""

from google.cloud.firestore import Client, CollectionReference, DocumentReference

from app.models.base import FirestoreModel
from app.models.business import business_subcollection


class ScannerSession(FirestoreModel):
    # "till": scans go into a selling-app till's cart. "admin": started from the web app by someone who manages
    # products; the phone only registers products (there is no cart to scan into).
    mode: str = "till"
    location_id: str
    location_name: str = ""
    till_device_id: str  # the till (one browser) that started it: each till has its own sessions
    till_uid: str  # who was signed in on the till
    till_name: str = ""
    active: bool = True
    expires_at: int  # the session ends by itself after a shift
    scanner_name: str = ""  # the phone, once paired
    paired_at: int | None = None
    last_scan_at: int | None = None


class Scan(FirestoreModel):
    barcode: str
    item_key: str  # the selling app's item: "productId__variantId" (or "productId__base")
    product_name: str
    scanned_by_name: str = ""


class ScannerPairing(FirestoreModel):
    business_id: str
    session_id: str
    expires_at: int


class ScannerSecret(FirestoreModel):
    """The paired phone's token, as a SHA-256 hash (the token itself is only ever on the phone)."""

    business_id: str
    session_id: str
    token_hash: str


def scanner_sessions_collection(db: Client, business_id: str) -> CollectionReference:
    return business_subcollection(db, business_id, "scannerSessions")


def scans_collection(db: Client, business_id: str, session_id: str) -> CollectionReference:
    return scanner_sessions_collection(db, business_id).document(session_id).collection("scans")


def pairing_document(db: Client, code: str) -> DocumentReference:
    return db.collection("scannerPairings").document(code)


def secret_document(db: Client, business_id: str, session_id: str) -> DocumentReference:
    return db.collection("scannerSecrets").document(f"{business_id}_{session_id}")
