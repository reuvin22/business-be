from pydantic import Field

from app.schemas.base import CamelModel, UrlText
from app.schemas.enums import ActiveStatus


class BrandIn(CamelModel):
    """A brand the business owns (section 11). Products point to a brand by id."""

    brand_name: str = Field(min_length=1)
    description: str = ""
    logo: UrlText = ""
    website: UrlText = ""
    status: ActiveStatus = ActiveStatus.ACTIVE
