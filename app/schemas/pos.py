"""The selling app (my-business-pos): seller accounts, checkout, receipts, and stock changes."""

import datetime

from pydantic import Field, field_validator, model_validator

from app.schemas.base import CamelModel, EmailText
from app.schemas.enums import MemberStatus, PosPaymentType

# ---- Seller accounts (managed from the main app's Team page) ---------------------------------


class SellerCreateIn(CamelModel):
    """A new seller account. The business sets the first password and tells the seller."""

    display_name: str = Field(min_length=1)
    email: EmailText
    password: str = Field(min_length=6, max_length=100)  # Firebase needs at least 6 characters
    location_id: str | None = None  # the store they sell from; None = any location


class SellerUpdateIn(CamelModel):
    display_name: str = Field(min_length=1)
    location_id: str | None = None
    status: MemberStatus = MemberStatus.ACTIVE


class SellerPasswordIn(CamelModel):
    password: str = Field(min_length=6, max_length=100)


# ---- Selling --------------------------------------------------------------------------------


class CheckoutLineIn(CamelModel):
    product_id: str = Field(min_length=1)
    variant_id: str | None = None
    quantity: int = Field(ge=1)


class CheckoutIn(CamelModel):
    """One sale at the counter: several products, paid together. The server works out the prices."""

    location_id: str = Field(min_length=1)
    items: list[CheckoutLineIn] = Field(min_length=1, max_length=100)
    payment_method: PosPaymentType = PosPaymentType.CASH
    amount_paid: float | None = Field(default=None, ge=0)  # empty = exactly the total
    note: str = ""
    date: datetime.date  # the seller's local date, so "today's sales" match their day


class VoidIn(CamelModel):
    reason: str = Field(min_length=1)


class StockChangeIn(CamelModel):
    """Stock received (+) or taken out (-) at the counter, e.g. +24 delivered, -2 damaged."""

    location_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    variant_id: str | None = None
    change: float
    note: str = ""

    @field_validator("change")
    @classmethod
    def not_zero(cls, change: float) -> float:
        if change == 0:
            raise ValueError("change cannot be 0")
        return change

    @model_validator(mode="after")
    def reason_for_removing(self):
        if self.change < 0 and not self.note:
            raise ValueError("say why stock is taken out (e.g. damaged, expired)")
        return self


# ---- What the selling app reads -------------------------------------------------------------


class PosPrice(CamelModel):
    """A price tier that applies at the counter today."""

    variant_id: str | None = None
    price: float
    minimum_quantity: int = 1
    maximum_quantity: int | None = None


class PosVariant(CamelModel):
    id: str
    variant_name: str
    sku: str = ""
    barcode: str = ""
    unit: str = ""


class PosProduct(CamelModel):
    """A product as the selling app shows it. Stock is not here: the app listens to it live."""

    id: str
    product_name: str
    sku: str = ""
    barcode: str = ""
    unit: str = "pcs"
    image_url: str = ""
    category_id: str | None = None
    variants: list[PosVariant] = []
    prices: list[PosPrice] = []


class PosLocation(CamelModel):
    id: str
    location_name: str


class PosBusiness(CamelModel):
    """A business the user can sell for, for the selling app's start screen."""

    id: str
    business_name: str
    business_logo: str = ""
    currency: str = "PHP"


class PosContext(CamelModel):
    """Everything the selling app needs to start: the business, who is selling, and where."""

    business: PosBusiness
    seller_name: str
    role: str
    can_void_any: bool  # managers can void anyone's receipt; sellers only their own, on the same day
    locations: list[PosLocation]  # a seller with a store sees only that one
    # True when e-wallet, card, and bank transfer are paid online through Xendit (a QR code at the till)
    online_payments: bool = False
