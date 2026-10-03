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

Changing the key (rotation): put the new key in DATA_ENCRYPTION_KEY and the old one in
DATA_ENCRYPTION_OLD_KEYS. New data uses the new key, and old data is still read with the old one. Then run
`python -m app.scripts.encrypt_existing --apply`, which re-encrypts everything with the new key; after that
the old key can be removed.
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


def _parse_key(text: str, name: str) -> bytes:
    try:
        key = base64.b64decode(text.strip(), validate=True)
    except binascii.Error:
        raise EncryptionKeyError(f"{name} must be base64 text") from None
    if len(key) != 32:
        raise EncryptionKeyError(f"{name} must be 32 bytes (44 characters of base64)")
    return key


@lru_cache(maxsize=1)
def master_key() -> bytes:
    text = settings.data_encryption_key.strip()
    if not text:
        raise EncryptionKeyError(
            "DATA_ENCRYPTION_KEY is not set. Make one with: "
            "python -c \"import os, base64; print(base64.b64encode(os.urandom(32)).decode())\""
        )
    return _parse_key(text, "DATA_ENCRYPTION_KEY")


@lru_cache(maxsize=1)
def old_master_keys() -> tuple[bytes, ...]:
    """Earlier keys (DATA_ENCRYPTION_OLD_KEYS), still used to READ data saved before a key change."""
    texts = [t for t in settings.data_encryption_old_keys.split(",") if t.strip()]
    return tuple(_parse_key(t, "DATA_ENCRYPTION_OLD_KEYS") for t in texts)


@lru_cache(maxsize=4096)
def _derive_with(master: bytes, purpose: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=f"siris:{purpose}".encode()).derive(master)


def _derive(purpose: str) -> bytes:
    """A separate key for each purpose (or chat room), so handing one out reveals nothing else."""
    return _derive_with(master_key(), purpose)


def _all_keys(purpose: str) -> list[bytes]:
    """The current key first, then the old ones (for data saved before a key change)."""
    return [_derive(purpose), *(_derive_with(old, purpose) for old in old_master_keys())]


def _seal(key: bytes, plaintext: bytes) -> str:
    nonce = os.urandom(NONCE_BYTES)
    return PREFIX + base64.urlsafe_b64encode(nonce + AESGCM(key).encrypt(nonce, plaintext, None)).decode()


def _open_any(keys: list[bytes], text: str) -> tuple[bytes, int]:
    """Decrypts with the first key that fits. Returns (plaintext, which key: 0 = the current one)."""
    raw = base64.urlsafe_b64decode(text[len(PREFIX) :])
    for index, key in enumerate(keys):
        try:
            return AESGCM(key).decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], None), index
        except InvalidTag:
            continue
    raise ValueError("Encrypted data could not be read: wrong DATA_ENCRYPTION_KEY, or the data was changed")


def _open(key: bytes, text: str) -> bytes:
    return _open_any([key], text)[0]


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
    return json.loads(_open_any(_all_keys(purpose), value)[0])


def needs_new_key(value, purpose: str = "data") -> bool:
    """True when the value is encrypted with an old key (re-encrypt it after a key change)."""
    return is_encrypted(value) and _open_any(_all_keys(purpose), value)[1] > 0


def reencrypt_value(value, purpose: str = "data") -> str:
    """The value encrypted with the current key (from plain, or from an old key)."""
    return _seal(_derive(purpose), json.dumps(decrypt_value(value, purpose), separators=(",", ":"), ensure_ascii=False).encode())


# ---- Text (the Redis cache) ------------------------------------------------------------------


def encrypt_text(text: str, purpose: str) -> str:
    return _seal(_derive(purpose), text.encode())


def decrypt_text(text: str, purpose: str) -> str:
    if not is_encrypted(text):
        raise ValueError("not encrypted")
    return _open_any(_all_keys(purpose), text)[0].decode()


# ---- Chat rooms (the Realtime Database; the browser decrypts) ---------------------------------


def _room_purpose(room: str, version: str) -> str:
    # Version "" is the first key of a room (and how rooms were keyed before versions existed)
    return f"room:{room}" if not version else f"room:{room}#v{version}"


def room_key(room: str, version: str = "") -> str:
    """The key of one chat room (e.g. "chat/dm/abc") at one version, as base64, for the browser (Web Crypto
    AES-GCM). A room gets a new version when someone who could read it leaves (see app/core/realtime.py)."""
    return base64.b64encode(_derive(_room_purpose(room, version))).decode()


def seal_for_room(room: str, value, version: str = "") -> str:
    return encrypt_value(value, _room_purpose(room, version))


def open_for_room(room: str, value, version: str = ""):
    return decrypt_value(value, _room_purpose(room, version))


def room_needs_new_key(room: str, value, version: str = "") -> bool:
    return needs_new_key(value, _room_purpose(room, version))


def reseal_for_room(room: str, value, version: str = "") -> str:
    return reencrypt_value(value, _room_purpose(room, version))


def check() -> dict:
    """For /api/health/encryption: is the key set and working?"""
    try:
        ok = decrypt_value(encrypt_value({"check": True})) == {"check": True}
    except (EncryptionKeyError, ValueError) as error:
        return {"status": "error", "detail": str(error)}
    return {"status": "ok" if ok else "error", "algorithm": "AES-256-GCM"}
