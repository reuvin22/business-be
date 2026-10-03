"""Encrypts the confidential data that was saved before encryption was turned on. Run it once, after setting
DATA_ENCRYPTION_KEY (the same key the API uses):

    python -m app.scripts.encrypt_existing          # shows what would change
    python -m app.scripts.encrypt_existing --apply  # changes it

New data is encrypted as it is saved; this only catches up the old data. Running it again is harmless:
values that are already encrypted are skipped.

It covers:
  - Firestore: the `encrypted_fields` of every model (see app/models/base.py)
  - the Realtime Database: chat messages and live activity (see app/core/realtime.py)
  - Redis: drops every cached entry (older entries were saved unencrypted)
"""

import sys

from google.cloud.firestore import Client

from app.core import cache, crypto, realtime
from app.core.firebase import get_db
from app.models.activity import Activity
from app.models.base import FirestoreModel
from app.models.business import Business
from app.models.member import Member
from app.models.network import Conversation, CustomerPrice, Message, Relationship, VerificationRequest
from app.models.pos import OnlinePayment, Receipt
from app.models.profile import BusinessDocument, Certification, Contact, PaymentMethod
from app.models.settings import LegalInfo, PaymentTerms
from app.models.trade import Order, Sale

# Top-level collections, and collections found under every business (or conversation): name -> model
TOP_LEVEL = {
    "businesses": Business,
    "relationships": Relationship,
    "conversations": Conversation,
    "verificationRequests": VerificationRequest,
    "orders": Order,
}
NESTED = {
    "members": Member,
    "contacts": Contact,
    "paymentMethods": PaymentMethod,
    "certifications": Certification,
    "documents": BusinessDocument,
    "customerPrices": CustomerPrice,
    "sales": Sale,
    "receipts": Receipt,
    "onlinePayments": OnlinePayment,
    "activity": Activity,
    "messages": Message,  # conversations/{id}/messages (from before the chat moved to the Realtime Database)
}
SETTINGS = {"legal": LegalInfo, "paymentTerms": PaymentTerms}  # businesses/{id}/settings/{name}


def _missing(model: type[FirestoreModel], data: dict) -> dict:
    """The fields of this document that should be encrypted but are not yet, encrypted."""
    plain = {alias: data[alias] for alias in model._aliases() if alias in data and not crypto.is_encrypted(data[alias])}
    return model.encrypt_fields(plain)


def encrypt_firestore(db: Client, apply: bool) -> int:
    changed = 0

    def fix(snapshot, model):
        nonlocal changed
        changes = _missing(model, snapshot.to_dict() or {})
        if changes:
            changed += 1
            print(f"  {snapshot.reference.path}: {', '.join(changes)}")
            if apply:
                snapshot.reference.update(changes)

    for name, model in TOP_LEVEL.items():
        for snapshot in db.collection(name).stream():
            fix(snapshot, model)
    for name, model in NESTED.items():
        for snapshot in db.collection_group(name).stream():
            fix(snapshot, model)
    for snapshot in db.collection_group("settings").stream():
        if snapshot.id in SETTINGS:
            fix(snapshot, SETTINGS[snapshot.id])
    return changed


def encrypt_realtime(apply: bool) -> int:
    store = realtime.get_store()
    changed = 0
    rooms: list[str] = [realtime.MARKET_PATH]
    rooms += [realtime.team_path(business_id) for business_id in (store.get("chat/team") or {})]
    rooms += [f"{realtime.dm_path(conversation_id)}/messages" for conversation_id in (store.get("chat/dm") or {})]
    rooms += [realtime.live_path(business_id) for business_id in (store.get("live") or {})]
    for path in rooms:
        for message_id, message in (store.get(path) or {}).items():
            plain = {k: message[k] for k in realtime.SECRET_FIELDS if message.get(k) is not None and not crypto.is_encrypted(message[k])}
            if plain:
                changed += 1
                print(f"  {path}/{message_id}: {', '.join(plain)}")
                if apply:
                    store.update(f"{path}/{message_id}", realtime.seal(path, plain))
    return changed


def clear_cache(apply: bool) -> int:
    client = cache.get_client()
    if client is None:
        return 0
    keys = list(client.scan_iter(f"{cache.KEY_PREFIX}:*"))
    if apply and keys:
        client.delete(*keys)
    return len(keys)


def main() -> None:
    apply = "--apply" in sys.argv
    if crypto.check()["status"] != "ok":
        sys.exit(f"Encryption is not set up: {crypto.check().get('detail')}")
    print("Firestore:")
    documents = encrypt_firestore(get_db(), apply)
    print("Realtime Database:")
    messages = encrypt_realtime(apply)
    entries = clear_cache(apply)
    verb = "Encrypted" if apply else "Would encrypt"
    print(f"\n{verb} {documents} documents and {messages} messages; {'dropped' if apply else 'would drop'} {entries} cache entries.")
    if not apply:
        print("Nothing was changed. Run again with --apply to do it.")


if __name__ == "__main__":
    main()
