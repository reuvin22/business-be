from pydantic import Field

from app.schemas.base import CamelModel
from app.schemas.enums import PaymentTerm, PaymentType


class PaymentMethodIn(CamelModel):
    """A way buyers can pay (section 14). Account details are private.

    Buyers only see the account details of the method they chose, after the seller confirms their order.
    """

    payment_type: PaymentType
    account_name: str = ""
    account_number: str = ""
    provider: str = ""  # e.g. BDO, BPI, GCash
    instructions: str = ""
    is_active: bool = True


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
