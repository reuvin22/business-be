import datetime

from pydantic import Field

from app.schemas.base import CamelModel


class SaleIn(CamelModel):
    """A walk-in / over-the-counter sale. Takes the quantity out of one location's stock."""

    product_id: str = Field(min_length=1)
    variant_id: str | None = None
    location_id: str = Field(min_length=1)
    quantity: int = Field(ge=1)
    unit_price: float = Field(ge=0)
    date: datetime.date
