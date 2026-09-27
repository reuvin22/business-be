import datetime

from app.schemas.base import CamelModel, UrlText
from app.schemas.enums import RegistrationType


class LegalIn(CamelModel):
    """Registration, tax, and permit details (section 2).

    Nothing is required, because what a business needs depends on its type.
    """

    registration_type: RegistrationType | None = None
    registration_number: str = ""
    registration_date: datetime.date | None = None
    tax_identification_number: str = ""  # BIR TIN
    tax_registered: bool = False
    vat_registered: bool = False
    business_permit_number: str = ""  # Mayor's / business permit
    business_permit_expiry: datetime.date | None = None
    license_number: str = ""  # industry-specific license
    license_expiry: datetime.date | None = None
    legal_document_urls: list[UrlText] = []
