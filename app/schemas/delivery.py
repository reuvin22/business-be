from pydantic import Field, model_validator

from app.schemas.base import CamelModel
from app.schemas.enums import DeliveryMethod


class DeliverySettingsIn(CamelModel):
    """How the business gets orders to buyers (section 13)."""

    delivery_available: bool = False
    pickup_available: bool = True
    shipping_available: bool = False
    delivery_radius_km: float | None = Field(default=None, ge=0)
    delivery_methods: list[DeliveryMethod] = []
    minimum_order_for_delivery: float | None = Field(default=None, ge=0)
    delivery_fee: float | None = Field(default=None, ge=0)  # used when no delivery zone matches
    free_delivery_threshold: float | None = Field(default=None, ge=0)  # orders at or above this ship free
    estimated_delivery_days: int | None = Field(default=None, ge=0)
    delivery_notes: str = ""


class DeliveryZoneIn(CamelModel):
    """A special fee for one area. The most specific match wins: barangay > city > province > region > country.
    The names come from the place pickers (see app/core/geo.py), so they match addresses picked the same way."""

    country: str = ""  # e.g. "Philippines" (empty = any country, for zones made before countries were added)
    region: str = ""
    province: str = ""
    city: str = ""
    barangay: str = ""
    delivery_fee: float = Field(default=0, ge=0)
    estimated_days: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def needs_an_area(self):
        if not (self.country or self.region or self.province or self.city or self.barangay):
            raise ValueError("choose at least a country")
        return self
