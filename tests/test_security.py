"""The fixes from the security review (SIRIS-Security-Review.pdf). No database needed."""

import base64
import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.controllers import member_controller, seller_controller
from app.controllers.pricing import trusted_buyer_types
from app.core import crypto, rate_limit
from app.core.config import settings
from app.dependencies.auth import is_platform_admin
from app.models.member import Member
from app.models.settings import ReturnPolicy
from app.schemas.chat import ChatMessageIn
from app.schemas.enums import BusinessType, MemberRole, Permission
from app.schemas.policies import ReturnPolicyIn
from app.schemas.pos import SellerPasswordIn
from app.schemas.trust import DocumentIn


def access_as(role=MemberRole.MANAGER, permissions=(Permission.MANAGE_MEMBERS, Permission.MANAGE_PRODUCTS)):
    member = Member(id="me", role=role, permissions=list(permissions))
    return SimpleNamespace(member=member, business_id="b1", user=SimpleNamespace(uid="me"))


# ---- 1. Seller password resets ------------------------------------------------------------------


def seller_access():
    return SimpleNamespace(require=lambda permission: None, business_id="b1")


def test_a_business_cannot_set_the_password_of_an_account_it_did_not_create(monkeypatch):
    their_own = Member(id="victim", role=MemberRole.SELLER, account_managed=False)
    monkeypatch.setattr(seller_controller, "_get_seller", lambda db, business_id, user_id: their_own)
    monkeypatch.setattr(seller_controller, "set_account_password", lambda *a: pytest.fail("password changed"))
    with pytest.raises(HTTPException) as refused:
        seller_controller.set_password(None, seller_access(), "victim", SellerPasswordIn(password="new-password-123"))
    assert refused.value.status_code == 403


def test_nor_of_a_login_another_business_also_uses(monkeypatch):
    made_here = Member(id="shared", role=MemberRole.SELLER, account_managed=True)
    monkeypatch.setattr(seller_controller, "_get_seller", lambda db, business_id, user_id: made_here)
    monkeypatch.setattr(seller_controller, "_used_elsewhere", lambda db, business_id, uid: True)
    monkeypatch.setattr(seller_controller, "set_account_password", lambda *a: pytest.fail("password changed"))
    with pytest.raises(HTTPException):
        seller_controller.set_password(None, seller_access(), "shared", SellerPasswordIn(password="new-password-123"))


def test_its_own_seller_login_can_be_reset(monkeypatch):
    made_here = Member(id="s1", role=MemberRole.SELLER, account_managed=True)
    changed = []
    monkeypatch.setattr(seller_controller, "_get_seller", lambda db, business_id, user_id: made_here)
    monkeypatch.setattr(seller_controller, "_used_elsewhere", lambda db, business_id, uid: False)
    monkeypatch.setattr(seller_controller, "set_account_password", lambda uid, password: changed.append(uid))
    seller_controller.set_password(None, seller_access(), "s1", SellerPasswordIn(password="new-password-123"))
    assert changed == ["s1"]


def test_seller_passwords_need_10_characters():
    with pytest.raises(ValidationError):
        SellerPasswordIn(password="short1")


# ---- 2. Platform admins -------------------------------------------------------------------------


def test_an_admin_email_counts_only_when_verified(monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", "boss@siris.ph")
    assert is_platform_admin({"email": "boss@siris.ph", "email_verified": True})
    assert not is_platform_admin({"email": "boss@siris.ph", "email_verified": False})  # someone signed up with it
    assert not is_platform_admin({"email": "boss@siris.ph"})
    assert is_platform_admin({"email": "anyone@x.com", "admin": True})  # the custom claim (set_admin.py)


# ---- 3. Permissions -----------------------------------------------------------------------------


def test_a_manager_cannot_give_permissions_they_lack():
    with pytest.raises(HTTPException):
        member_controller.check_can_grant(access_as(), [Permission.MANAGE_INVENTORY])


def test_nobody_but_the_owner_gives_team_or_payment_control():
    manager = access_as(permissions=(Permission.MANAGE_MEMBERS, Permission.MANAGE_PAYMENTS))
    for permission in (Permission.MANAGE_MEMBERS, Permission.MANAGE_PAYMENTS):
        with pytest.raises(HTTPException):
            member_controller.check_can_grant(manager, [permission])
    member_controller.check_can_grant(access_as(role=MemberRole.OWNER, permissions=()), [Permission.MANAGE_MEMBERS])


def test_a_manager_may_give_what_they_have():
    member_controller.check_can_grant(access_as(), [Permission.MANAGE_PRODUCTS])


def test_a_manager_cannot_change_someone_more_powerful():
    boss = Member(id="boss", role=MemberRole.ADMIN, permissions=[Permission.MANAGE_MEMBERS, Permission.MANAGE_PAYMENTS])
    with pytest.raises(HTTPException):
        member_controller.check_can_manage(access_as(), boss)
    staff = Member(id="staff", role=MemberRole.STAFF, permissions=[Permission.MANAGE_PRODUCTS])
    member_controller.check_can_manage(access_as(), staff)


# ---- 4 and 8. Files must be uploaded to SIRIS -------------------------------------------------------


@pytest.fixture
def storage_set_up(monkeypatch):
    monkeypatch.setattr(settings, "r2_public_url", "https://files.siris.ph")
    monkeypatch.setattr(settings, "r2_old_public_urls", "https://pub-old.r2.dev")


def test_links_to_other_websites_are_refused(storage_set_up):
    with pytest.raises(ValidationError):
        ChatMessageIn(message="hi", attachments=["https://tracker.example.com/pixel.png"])
    with pytest.raises(ValidationError):
        ReturnPolicyIn(policy_file_url="https://evil.example.com/fake-login.html")
    ChatMessageIn(message="hi", attachments=["https://files.siris.ph/chat_img/b1/a.png"])
    ChatMessageIn(message="hi", attachments=["https://pub-old.r2.dev/chat_img/b1/a.png"])  # the earlier address


def test_private_documents_take_private_files(storage_set_up):
    DocumentIn(document_type="BUSINESS_PERMIT", file_url="private:private_docs/b1/permit.pdf")
    with pytest.raises(ValidationError):
        DocumentIn(document_type="BUSINESS_PERMIT", file_url="https://drive.google.com/permit")
    with pytest.raises(ValidationError):  # a public file cannot be "private"
        ChatMessageIn(message="hi", attachments=["private:private_docs/b1/permit.pdf"])


def test_saved_records_still_load(storage_set_up):
    """Data saved before the rule existed is read as it is."""
    policy = ReturnPolicy.model_validate({"policyFileUrl": "https://old.example.com/policy.pdf"})
    assert policy.policy_file_url == "https://old.example.com/policy.pdf"


# ---- 5. Prices for a customer type ----------------------------------------------------------------


def test_type_prices_only_for_connected_buyers():
    types = [BusinessType.DISTRIBUTOR]
    assert trusted_buyer_types(False, types) == []  # anyone can call themselves a distributor
    assert trusted_buyer_types(True, types) == types


# ---- 9. Rate limits -------------------------------------------------------------------------------


def test_too_many_requests_are_refused():
    rate_limit.reset()
    limit = rate_limit.Limit("test", 3, 60)
    assert [rate_limit.hit("u:tester", limit) for _ in range(3)] == [None, None, None]
    assert rate_limit.hit("u:tester", limit) is not None
    assert rate_limit.hit("u:someone-else", limit) is None


def test_upload_quota():
    rate_limit.reset()
    assert rate_limit.use_quota("upload:b1", 600, 1000, 60)
    assert not rate_limit.use_quota("upload:b1", 600, 1000, 60)
    assert rate_limit.use_quota("upload:b1", 400, 1000, 60)


def test_requests_are_counted_per_login():
    assert rate_limit.caller_key("Bearer abc", "1.2.3.4") == rate_limit.caller_key("Bearer abc", "5.6.7.8")
    assert rate_limit.caller_key("", "1.2.3.4") == "ip:1.2.3.4"


# ---- 12. Changing the encryption key ----------------------------------------------------------------


def test_old_data_is_read_after_a_key_change(monkeypatch):
    old_value = crypto.encrypt_value({"tin": "123-456-789"})
    old_key = settings.data_encryption_key
    monkeypatch.setattr(settings, "data_encryption_key", base64.b64encode(b"n" * 32).decode())
    monkeypatch.setattr(settings, "data_encryption_old_keys", old_key)
    crypto.master_key.cache_clear()
    crypto.old_master_keys.cache_clear()
    try:
        assert crypto.decrypt_value(old_value) == {"tin": "123-456-789"}
        assert crypto.needs_new_key(old_value)
        fresh = crypto.reencrypt_value(old_value)
        assert not crypto.needs_new_key(fresh) and crypto.decrypt_value(fresh) == {"tin": "123-456-789"}
    finally:
        monkeypatch.undo()
        crypto.master_key.cache_clear()
        crypto.old_master_keys.cache_clear()


# ---- 18. Text limits ------------------------------------------------------------------------------


def test_huge_text_is_refused():
    with pytest.raises(ValidationError):
        ReturnPolicyIn(policy_description="x" * 50_000)


# ---- 7. Sale dates ----------------------------------------------------------------------------------


def test_a_sale_cannot_be_backdated():
    from app.controllers import pos_controller
    from app.schemas.pos import CheckoutIn

    a_month_ago = datetime.datetime.now(datetime.UTC).date() - datetime.timedelta(days=30)
    cart = CheckoutIn(location_id="l1", items=[{"productId": "p1", "quantity": 1}], date=a_month_ago)
    with pytest.raises(HTTPException) as refused:
        pos_controller._price_cart(None, None, cart, None)  # refused before anything is read
    assert refused.value.status_code == 400
