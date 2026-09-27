from pydantic import Field, field_validator

from app.schemas.base import CamelModel


class InventoryIn(CamelModel):
    """Stock of one product (or variant) at one location (section 8)."""

    product_id: str = Field(min_length=1)
    variant_id: str | None = None
    location_id: str = Field(min_length=1)
    quantity: float = Field(ge=0)
    reorder_level: float | None = Field(default=None, ge=0)  # at or below this = LOW_STOCK


class InventoryUpdateIn(CamelModel):
    quantity: float = Field(ge=0)
    reorder_level: float | None = Field(default=None, ge=0)


class InventoryAdjustIn(CamelModel):
    """Add or remove stock, e.g. +100 for a delivery, -3 for damaged goods."""

    change: float
    note: str = ""

    @field_validator("change")
    @classmethod
    def not_zero(cls, change: float) -> float:
        if change == 0:
            raise ValueError("change cannot be 0")
        return change
