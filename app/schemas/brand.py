from pydantic import Field, model_validator

from app.schemas.base import CamelModel, UrlText, require_own_files
from app.schemas.enums import ActiveStatus


class BrandIn(CamelModel):
    """A brand the business owns (section 11). Products point to a brand by id."""

    brand_name: str = Field(min_length=1)
    description: str = ""
    logo: UrlText = ""
    website: UrlText = ""
    status: ActiveStatus = ActiveStatus.ACTIVE

    @model_validator(mode="after")
    def uploaded_logo(self):
        require_own_files(self, [self.logo], "Brand logo")
        return self
