from pydantic import Field

from app.schemas.base import CamelModel
from app.schemas.enums import ActiveStatus


class CategoryIn(CamelModel):
    """A shared product/business category (section 12). Categories form a tree:

    Food > Beverages > Soft Drinks
    """

    category_name: str = Field(min_length=1)
    parent_category_id: str | None = None  # None = top level
    status: ActiveStatus = ActiveStatus.ACTIVE
