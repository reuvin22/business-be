from pydantic import Field

from app.schemas.base import CamelModel, EmailText, UrlText
from app.schemas.enums import BusinessSize, BusinessStatus, BusinessType, Permission, VerificationStatus, VerificationType


class BusinessIn(CamelModel):
    """Core business details that the owner fills in (section 1 of the spec)."""

    business_name: str = Field(min_length=1, max_length=200)
    legal_name: str = ""
    trade_name: str = ""
    # A business can be several types at once, e.g. MANUFACTURER + WHOLESALER
    business_types: list[BusinessType] = Field(min_length=1)
    business_description: str = ""
    business_logo: UrlText = ""
    cover_image: UrlText = ""
    year_established: int | None = Field(default=None, ge=1800, le=2100)
    business_size: BusinessSize | None = None
    industry: str = ""
    category_ids: list[str] = []  # ids from the shared categories list
    business_status: BusinessStatus = BusinessStatus.ACTIVE
    website: UrlText = ""
    primary_email: EmailText = ""
    primary_phone: str = ""
    currency: str = Field(default="PHP", min_length=3, max_length=3)


class BusinessSummary(CamelModel):
    """What other businesses see in the directory list."""

    id: str
    business_name: str
    trade_name: str
    business_types: list[BusinessType]
    business_description: str
    business_logo: str
    cover_image: str
    industry: str
    category_ids: list[str]
    verification_status: VerificationStatus
    verification_level: VerificationType | None
    rating_average: float
    rating_count: int
    capabilities: list[str]
    primary_city: str
    primary_province: str
    currency: str


class BusinessPublicDetails(BusinessSummary):
    """Extra identity details shown on a business's public profile page."""

    legal_name: str
    year_established: int | None
    business_size: BusinessSize | None
    website: str
    primary_email: str
    primary_phone: str
    created_at: int


class MyRole(CamelModel):
    """The logged-in user's role and permissions in one business."""

    role: str
    permissions: list[Permission]
