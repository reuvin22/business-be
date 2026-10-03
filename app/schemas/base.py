import datetime
import re
from typing import Annotated, ClassVar

from pydantic import AfterValidator, BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.core.config import settings

# The longest text any field accepts (a long return policy fits; a megabyte of junk does not)
MAX_TEXT_LENGTH = 20_000


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
        str_max_length=MAX_TEXT_LENGTH,
    )

    # True for what is read back from the database (FirestoreModel and the views built from it). Checks
    # that only apply to what users send (e.g. "files must be uploaded to SIRIS") skip stored records, so
    # data saved before a check existed still loads.
    stored_record: ClassVar[bool] = False


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


# ---- Files: only what was uploaded to SIRIS ---------------------------------------------------

PRIVATE_FILE_PREFIX = "private:"  # a file in the private bucket (see app/core/storage.py), opened with a signed link


def _file_prefixes() -> list[str]:
    """Where SIRIS's public files live: R2_PUBLIC_URL (and R2_OLD_PUBLIC_URLS, after a change of address)."""
    urls = [settings.r2_public_url, *settings.r2_old_public_urls.split(",")]
    return [url.strip().rstrip("/") + "/" for url in urls if url.strip()]


def is_own_file(url: str, private_allowed: bool = False) -> bool:
    """Is this a file uploaded to SIRIS (not a link to some other website)?"""
    if not url:
        return True
    if url.startswith(PRIVATE_FILE_PREFIX):
        return private_allowed and ".." not in url
    prefixes = _file_prefixes()
    if not prefixes:  # file storage is not set up (local development): any link
        return url.startswith(("http://", "https://"))
    return url.startswith(tuple(prefixes))


def require_own_files(model: CamelModel, urls: list[str], what: str, private_allowed: bool = False) -> None:
    """Refuses links to other websites where SIRIS shows a file (an image, a PDF): such a link could show a
    fake page inside SIRIS, or track who opens it. Stored records are not checked (see stored_record)."""
    if model.stored_record:
        return
    if any(not is_own_file(url, private_allowed) for url in urls):
        raise ValueError(f"{what}: upload the file to SIRIS instead of linking to another website")

