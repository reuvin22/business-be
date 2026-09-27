import datetime
import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base for all schemas and models.

    Python code uses snake_case (created_at) but the JSON sent to and from the
    frontend, and the fields saved in Firestore, use camelCase (createdAt).
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,  # also accept snake_case names
        from_attributes=True,  # allow building a schema from another object with the same fields
        str_strip_whitespace=True,  # "  Sunrise Bakery " is saved as "Sunrise Bakery"
    )


# ---- Reusable field types ------------------------------------------------------------
# Use these like normal types:  website: UrlText = ""


def _check_url(value: str) -> str:
    if value and not value.startswith(("http://", "https://")):
        raise ValueError("must be a link starting with http:// or https://")
    return value


def _check_email(value: str) -> str:
    if value and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        raise ValueError("must be a valid email address")
    return value.lower()


def _check_time(value: str) -> str:
    if value and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError("must be a time like 08:00 or 17:30")
    return value


UrlText = Annotated[str, AfterValidator(_check_url)]  # "" or a link
EmailText = Annotated[str, AfterValidator(_check_email)]  # "" or an email
TimeText = Annotated[str, AfterValidator(_check_time)]  # "" or "HH:MM" (24-hour)


def check_date_order(start: datetime.date | None, end: datetime.date | None, message: str) -> None:
    """Raises an error when both dates are set and the end is before the start."""
    if start and end and end < start:
        raise ValueError(message)
