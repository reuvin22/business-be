from app.schemas.base import CamelModel
from app.schemas.enums import MediaType


class OpenedFile(CamelModel):
    """A link to a private file. It stops working after a few minutes."""

    url: str


class UploadedFile(CamelModel):
    """Where an uploaded image or video can be seen."""

    url: str
    media_type: MediaType
