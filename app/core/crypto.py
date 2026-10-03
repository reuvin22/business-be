"""Encryption of confidential data at rest (AES-256-GCM).

What is encrypted, and where:
  - Firestore: the fields a model lists in `encrypted_fields` (e.g. permit and tax numbers, payment account
    numbers, order and receipt lines and totals, message text). See FirestoreModel in app/models/base.py.
  - Redis: every cached value (the cache holds decrypted models, so the whole entry is encrypted).
  - Realtime Database: the content of chat messages and live activity. Each chat has its own key, derived
    from the master key, which the API hands only to the users allowed to read that chat; the browser
    decrypts with it (see `room_key`).

The API decrypts before answering, so the apps receive plain data over HTTPS and show it as usual.
Passwords are not here: Firebase Authentication keeps only a salted hash (scrypt) of each password,
which is safer than encryption because nobody, not even this API, can turn it back into the password.

An encrypted value is text:  "enc1:" + base64url(12-byte nonce + ciphertext + 16-byte tag), where the
plaintext is the value as JSON. Values without the prefix (saved before encryption was turned on) are
read as they are, and encrypted the next time they are saved.

The key is DATA_ENCRYPTION_KEY (32 random bytes, base64). Keep it secret and never lose it: without it
the encrypted data cannot be read. Make one with:
  python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"
"""

import base64
import binascii
import json
import os
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings

PREFIX = "enc1:"
NONCE_BYTES = 12


class EncryptionKeyError(RuntimeError):
    """DATA_ENCRYPTION_KEY is missing or not 32 bytes of base64."""


@lru_cache(maxsize=1)
def master_key() -> bytes:
    text = settings.data_encryption_key.strip()
    if not text:
        raise EncryptionKeyError(
            "DATA_ENCRYPTION_KEY is not set. Make one with: "
            "python -c \"import os, base64; print(base64.b64encode(os.urandom(32)).decode())\""
        )
    try:
        key = base64.b64decode(text, validate=True)
    except binascii.Error:
        raise EncryptionKeyError("DATA_ENCRYPTION_KEY must be base64 text") from None
    if len(key) != 32:
        raise EncryptionKeyError("DATA_ENCRYPTION_KEY must be 32 bytes (44 characters of base64)")
    return key


@lru_cache(maxsize=1024)
def _derive(purpose: str) -> bytes:
    """A separate key for each purpose (or chat room), so handing one out reveals nothing else."""
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=f"siris:{purpose}".encode()).derive(master_key())


def _seal(key: bytes, plaintext: bytes) -> str:
    nonce = os.urandom(NONCE_BYTES)
    return PREFIX + base64.urlsafe_b64encode(nonce + AESGCM(key).encrypt(nonce, plaintext, None)).decode()


def _open(key: bytes, text: str) -> bytes:
    raw = base64.urlsafe_b64decode(text[len(PREFIX) :])
    try:
        return AESGCM(key).decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], None)
    except InvalidTag:
        raise ValueError("Encrypted data could not be read: wrong DATA_ENCRYPTION_KEY, or the data was changed") from None


def is_encrypted(value) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


# ---- Values (Firestore fields) ---------------------------------------------------------------


def encrypt_value(value, purpose: str = "data") -> str:
    """Any JSON value -> encrypted text. Already-encrypted text is left as it is."""
    if is_encrypted(value):
        return value
    return _seal(_derive(purpose), json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


def decrypt_value(value, purpose: str = "data"):
    """The value encrypt_value encrypted. Anything that is not encrypted comes back unchanged."""
    if not is_encrypted(value):
        return value
    return json.loads(_open(_derive(purpose), value))


# ---- Text (the Redis cache) ------------------------------------------------------------------


def encrypt_text(text: str, purpose: str) -> str:
    return _seal(_derive(purpose), text.encode())


def decrypt_text(text: str, purpose: str) -> str:
    if not is_encrypted(text):
        raise ValueError("not encrypted")
    return _open(_derive(purpose), text).decode()


# ---- Chat rooms (the Realtime Database; the browser decrypts) ---------------------------------


def room_key(room: str) -> str:
    """The key of one chat room (e.g. "chat/dm/abc"), as base64, for the browser (Web Crypto AES-GCM)."""
    return base64.b64encode(_derive(f"room:{room}")).decode()


def seal_for_room(room: str, value) -> str:
    return encrypt_value(value, f"room:{room}")


def open_for_room(room: str, value):
    return decrypt_value(value, f"room:{room}")


def check() -> dict:
    """For /api/health/encryption: is the key set and working?"""
    try:
        ok = decrypt_value(encrypt_value({"check": True})) == {"check": True}
    except (EncryptionKeyError, ValueError) as error:
        return {"status": "error", "detail": str(error)}
    return {"status": "ok" if ok else "error", "algorithm": "AES-256-GCM"}
