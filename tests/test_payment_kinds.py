"""Payment methods: the type is the kind (bank transfer, e-wallet, card...), the provider says which one."""

from app.controllers import payment_method_controller
from app.models.profile import PaymentMethod
from app.schemas.enums import PaymentType
from app.schemas.payment import PaymentMethodIn, payment_kind


def test_older_methods_become_a_kind_and_a_provider():
    gcash = PaymentMethodIn(payment_type="GCASH", account_number="09171234567")
    assert (gcash.payment_type, gcash.provider, gcash.account_number) == (PaymentType.E_WALLET, "GCash", "09171234567")

    card = PaymentMethodIn(payment_type="CREDIT_CARD", provider="Visa")
    assert (card.payment_type, card.provider) == (PaymentType.CARD, "Visa")  # a provider that was set is kept


def test_only_the_details_a_kind_uses_are_kept():
    cash = PaymentMethodIn(payment_type="CASH", provider="BDO", account_name="Acme", account_number="123")
    assert (cash.provider, cash.account_name, cash.account_number) == ("", "", "")

    card = PaymentMethodIn(payment_type="CARD", provider="Credit cards", account_number="4111")
    assert (card.provider, card.account_number) == ("Credit cards", "")  # no account to pay into

    bank = PaymentMethodIn(payment_type="BANK_TRANSFER", provider="BDO", account_name="Acme", account_number="0012")
    assert (bank.provider, bank.account_number) == ("BDO", "0012")


def test_orders_made_with_an_older_kind_still_match():
    assert payment_kind(PaymentType.MAYA) == PaymentType.E_WALLET
    assert payment_kind(PaymentType.BANK_TRANSFER) == PaymentType.BANK_TRANSFER
    assert payment_kind(None) is None


def test_the_public_profile_names_the_providers_but_not_the_accounts(monkeypatch):
    methods = [
        PaymentMethod(id="1", payment_type="E_WALLET", provider="GCash", account_number="0917"),
        PaymentMethod(id="2", payment_type="GCASH", account_number="0918"),  # an older one: also GCash
        PaymentMethod(id="3", payment_type="E_WALLET", provider="Maya"),
        PaymentMethod(id="4", payment_type="CASH"),
        PaymentMethod(id="5", payment_type="BANK_TRANSFER", provider="BPI", is_active=False),
    ]
    monkeypatch.setattr(payment_method_controller, "list_payment_methods", lambda db, business_id: methods)
    accepted = payment_method_controller.list_accepted_payments(None, "b1")
    assert [(a.payment_type, a.providers) for a in accepted] == [("CASH", []), ("E_WALLET", ["GCash", "Maya"])]
    assert "0917" not in str([a.model_dump() for a in accepted])
