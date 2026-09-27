from pydantic import Field, field_validator, model_validator

from app.schemas.base import CamelModel, TimeText
from app.schemas.enums import DayOfWeek, LocationType


class TimeRange(CamelModel):
    start: TimeText = Field(min_length=1)
    end: TimeText = Field(min_length=1)

    @model_validator(mode="after")
    def check_order(self):
        # "HH:MM" text compares correctly: "08:00" < "17:00"
        if self.end <= self.start:
            raise ValueError("break end must be after its start")
        return self


class DayHours(CamelModel):
    """Opening hours for one day (section 5). Example: MONDAY 08:00-17:00, break 12:00-13:00."""

    day: DayOfWeek
    opening_time: TimeText = ""
    closing_time: TimeText = ""
    is_closed: bool = False
    break_periods: list[TimeRange] = []

    @model_validator(mode="after")
    def check_times(self):
        if self.is_closed:
            return self
        if not self.opening_time or not self.closing_time:
            raise ValueError(f"{self.day}: set opening and closing time, or mark the day as closed")
        if self.closing_time <= self.opening_time:
            raise ValueError(f"{self.day}: closing time must be after opening time")
        return self


class LocationIn(CamelModel):
    """A head office, warehouse, store, ... (section 4). Opening hours are kept inside the location."""

    location_name: str = Field(min_length=1)
    location_type: LocationType
    address_line_1: str = ""
    address_line_2: str = ""
    barangay: str = ""
    city: str = ""
    province: str = ""
    region: str = ""
    postal_code: str = ""
    country: str = "Philippines"
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    contact_phone: str = ""
    operating_hours: list[DayHours] = []
    is_primary: bool = False

    @field_validator("operating_hours")
    @classmethod
    def one_entry_per_day(cls, hours: list[DayHours]) -> list[DayHours]:
        days = [h.day for h in hours]
        if len(days) != len(set(days)):
            raise ValueError("each day can only appear once")
        return hours
