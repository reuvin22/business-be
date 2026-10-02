from app.schemas.base import CamelModel
from app.schemas.enums import MediaType


class UploadedFile(CamelModel):
    """Where an uploaded image or video can be seen."""

    url: str
    media_type: MediaType
