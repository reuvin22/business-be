"""Confidential data is encrypted at rest (app/core/crypto.py) and read back as it was."""

import json

import pytest

from app.core import cache, crypto, realtime
from app.models import activity, business, member, network, pos, profile, settings, trade
from app.models.base import FirestoreModel
from app.models.profile import PaymentMethod
from app.models.trade import Order
from app.schemas.enums import PaymentType


def all_models():
    found = set()
    for module in (activity, business, member, network, pos, profile, settings, trade):
        for value in vars(module).values():
            if isinstance(value, type) and issubclass(value, FirestoreModel) and value is not FirestoreModel:
                found.add(value)
    return found


def test_every_encrypted_field_exists():
    for model in all_models():
        for name in model.encrypted_fields:
            assert name in model.model_fields, f"{model.__name__}.{name}"


def test_values_round_trip_and_are_unreadable():
    for value in ["0917 123 4567", 1234.5, {"a": [1, "x"]}, [], None, "", "2026-10-03"]:
        sealed = crypto.encrypt_value(value)
        assert crypto.is_encrypted(sealed)
        assert crypto.decrypt_value(sealed) == value
    secret = crypto.encrypt_value("TIN 123-456-789")
    assert "123" not in secret
    assert crypto.encrypt_value("same") != crypto.encrypt_value("same")  # a fresh nonce every time


def test_plain_values_from_before_encryption_still_read():
    assert crypto.decrypt_value("plain text") == "plain text"
    assert crypto.decrypt_value(42) == 42


def test_tampered_data_is_refused():
    sealed = crypto.encrypt_value("secret")
    flipped = sealed[:-2] + ("A" if sealed[-2] != "A" else "B") + sealed[-1]
    with pytest.raises(ValueError):
        crypto.decrypt_value(flipped)


def test_model_fields_are_encrypted_in_firestore_only():
    method = PaymentMethod(payment_type=PaymentType.BANK_TRANSFER, provider="BDO", account_name="Juan", account_number="001234567890")
    saved = method.to_firestore()
    assert crypto.is_encrypted(saved["accountNumber"]) and crypto.is_encrypted(saved["accountName"])
    assert saved["paymentType"] == "BANK_TRANSFER"  # not confidential: stays readable
    assert PaymentMethod.model_validate({**PaymentMethod.decrypt_fields(saved), "id": "x"}).account_number == "001234567890"


def test_order_amounts_and_lines_are_encrypted():
    fields = Order.encrypted_fields
    assert {"items", "total", "shipping_address"} <= set(fields)
    assert "orderedAt" not in fields and "business_ids" not in fields  # queried: must stay readable


def test_cache_entries_are_encrypted(fake_redis, monkeypatch):
    monkeypatch.setattr(cache.settings, "redis_url", "redis://fake")  # the cache is only used when Redis is set up
    cache.remember("s", "k", lambda: {"total": 999.5}, to_json=lambda v: v, from_json=lambda v: v)
    stored = [fake_redis.get(key) for key in fake_redis.scan_iter("mb:*") if ":k" in key]
    assert stored and crypto.is_encrypted(stored[0]) and "999" not in stored[0]
    assert cache.remember("s", "k", lambda: None, to_json=lambda v: v, from_json=lambda v: v) == {"total": 999.5}


def test_realtime_messages_are_sealed_per_room():
    path = realtime.dm_path("conv1") + "/messages"
    sealed = realtime.seal(path, {"message": "price is 50", "attachments": [], "senderUid": "u", "createdAt": 1})
    assert crypto.is_encrypted(sealed["message"]) and sealed["senderUid"] == "u" and sealed["createdAt"] == 1
    assert realtime.unseal(path, sealed)["message"] == "price is 50"
    # Another room's key cannot read it
    with pytest.raises(ValueError):
        realtime.unseal(realtime.dm_path("conv2") + "/messages", sealed)
    assert realtime.room_key(path) != realtime.room_key(realtime.dm_path("conv2"))
    assert realtime.room_of(f"{path}/m1") == "chat/dm/conv1"
    assert realtime.room_of(realtime.live_path("b1") + "/a1") == "live/b1"


def test_browser_format_matches(monkeypatch):
    """The browser decrypts with Web Crypto: AES-GCM, 12-byte nonce, tag at the end, JSON inside."""
    import base64

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    room = "chat/team/b1"
    sealed = crypto.seal_for_room(room, "hello")
    raw = base64.urlsafe_b64decode(sealed[len(crypto.PREFIX) :])
    key = base64.b64decode(crypto.room_key(room))
    assert json.loads(AESGCM(key).decrypt(raw[:12], raw[12:], None)) == "hello"
