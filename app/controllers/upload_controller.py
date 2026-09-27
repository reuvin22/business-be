"""Uploading images (product photos) to Cloudflare R2."""

from fastapi import HTTPException, UploadFile, status

from app.controllers.crud import bad_request, forbidden
from app.core import storage
from app.core.config import settings
from app.dependencies.business_access import BusinessAccess
from app.schemas.enums import Permission


def detect_image_type(data: bytes) -> str | None:
    """The real type of an image, from its first bytes (we don't trust the name or the browser)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def upload_business_image(access: BusinessAccess, file: UploadFile) -> str:
    """Checks the file and stores it in the business's image folder. Returns the image URL."""
    if not (access.can(Permission.MANAGE_PRODUCTS) or access.can(Permission.EDIT_BUSINESS)):
        raise forbidden("You need the 'products.manage' or 'business.edit' permission to upload images")
    if not settings.r2_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image uploads are not set up yet (R2 settings are missing on the server)",
        )

    # Read one byte more than allowed, so we know when a file is too big without reading all of it
    data = file.file.read(storage.MAX_IMAGE_BYTES + 1)
    if len(data) > storage.MAX_IMAGE_BYTES:
        raise bad_request("The image is too big (5 MB at most)")
    content_type = detect_image_type(data)
    if content_type is None:
        raise bad_request("Please choose a JPG, PNG, WEBP, or GIF image")

    return storage.upload_image(data, content_type, folder=f"businesses/{access.business_id}/images")
