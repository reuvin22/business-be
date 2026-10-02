from pydantic import Field, model_validator

from app.schemas.base import CamelModel
from app.schemas.enums import PaymentTerm, PaymentType


# The older kinds that named a provider -> the kind, and the provider they meant
LEGACY_PAYMENT_TYPES = {
    PaymentType.GCASH: (PaymentType.E_WALLET, "GCash"),
    PaymentType.MAYA: (PaymentType.E_WALLET, "Maya"),
    PaymentType.CREDIT_CARD: (PaymentType.CARD, "Credit cards"),
    PaymentType.DEBIT_CARD: (PaymentType.CARD, "Debit cards"),
}

# Kinds that have an account to pay into (bank account, e-wallet number). Cash, cards, cheques... do not.
WITH_ACCOUNT = {PaymentType.BANK_TRANSFER, PaymentType.E_WALLET}


def payment_kind(payment_type: PaymentType | None) -> PaymentType | None:
    """GCASH -> E_WALLET, CREDIT_CARD -> CARD; the new kinds stay as they are."""
    return LEGACY_PAYMENT_TYPES.get(payment_type, (payment_type, ""))[0] if payment_type else None


class PaymentMethodIn(CamelModel):
    """A way buyers can pay (section 14). Account details are private.

    payment_type is the kind (bank transfer, e-wallet, card...); provider says which one (BDO, GCash, Visa...).
    Buyers only see the account details of the method they chose, after the seller confirms their order.
    """

    payment_type: PaymentType
    account_name: str = ""
    account_number: str = ""  # bank account number, or the e-wallet's mobile number
    provider: str = ""  # the bank (BDO, BPI), the e-wallet (GCash, Maya), or the cards (Visa, Credit cards)
    instructions: str = ""
    is_active: bool = True

    @model_validator(mode="after")
    def one_kind_one_provider(self):
        # An older method ("GCash" as the type) becomes the kind + provider ("E-wallet", "GCash")
        if self.payment_type in LEGACY_PAYMENT_TYPES:
            self.payment_type, provider = LEGACY_PAYMENT_TYPES[self.payment_type]
            self.provider = self.provider or provider
        if self.payment_type not in WITH_ACCOUNT:
            self.account_name = ""
            self.account_number = ""
        if self.payment_type in (PaymentType.CASH, PaymentType.COD):
            self.provider = ""
        return self


class AcceptedPayment(CamelModel):
    """Public: a kind of payment the business accepts, and which ones, e.g. E_WALLET with ["GCash", "Maya"]."""

    payment_type: PaymentType
    providers: list[str] = []


class PaymentInstructions(CamelModel):
    """What a buyer sees to pay a confirmed order."""

    payment_type: PaymentType
    account_name: str
    account_number: str
    provider: str
    instructions: str


class PaymentTermsIn(CamelModel):
    """Payment terms the business offers (section 15), e.g. COD, 50% down, NET 30."""

    payment_terms: list[PaymentTerm] = []
    credit_limit: float | None = Field(default=None, ge=0)
    credit_days: int | None = Field(default=None, ge=0)
    down_payment_percentage: float | None = Field(default=None, ge=0, le=100)
    notes: str = ""
