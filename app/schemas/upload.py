from app.schemas.base import CamelModel


class UploadedImage(CamelModel):
    """Where an uploaded image can be seen."""

    url: str
