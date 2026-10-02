"""Uploading product photos and videos, and the business logo and cover, to Cloudflare R2."""

from fastapi import HTTPException, UploadFile, status

from app.controllers.crud import bad_request, forbidden
from app.core import storage
from app.core.config import settings
from app.dependencies.business_access import BusinessAccess
from app.schemas.enums import MediaType, Permission


def detect_file_type(data: bytes) -> str | None:
    """The real type of an image or video, from its first bytes (we don't trust the name or the browser)."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp":  # MP4 and MOV share this layout; the brand after "ftyp" tells them apart
        return "video/quicktime" if data[8:12] == b"qt  " else "video/mp4"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    return None


# Each kind has its own folder at the top of the bucket, then one folder per business.
# Products can have videos too; the logo and cover must be images.
UPLOAD_KINDS = {
    "product": ("product_img", Permission.MANAGE_PRODUCTS, storage.ALLOWED_TYPES),
    "business": ("business_img", Permission.EDIT_BUSINESS, storage.ALLOWED_IMAGE_TYPES),
}


def upload_business_file(access: BusinessAccess, file: UploadFile, kind: str = "product") -> tuple[str, MediaType]:
    """Checks the file and stores it in the folder for its kind. Returns its URL and whether it is an image or video.

    kind: "product" (product photos and videos) or "business" (logo, cover)."""
    if kind not in UPLOAD_KINDS:
        raise bad_request("kind must be 'product' or 'business'")
    folder, permission, allowed = UPLOAD_KINDS[kind]
    if not access.can(permission):
        raise forbidden(f"You need the '{permission.value}' permission to upload this file")
    if not settings.r2_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Uploads are not set up yet (R2 settings are missing on the server)",
        )

    # Read one byte more than allowed, so we know when a file is too big without reading all of it
    data = file.file.read(storage.MAX_FILE_BYTES + 1)
    if len(data) > storage.MAX_FILE_BYTES:
        raise bad_request("The file is too big (25 MB at most)")
    content_type = detect_file_type(data)
    if content_type not in allowed:
        if allowed is storage.ALLOWED_IMAGE_TYPES:
            raise bad_request("Please choose a JPG, PNG, WEBP, or GIF image")
        raise bad_request("Please choose a JPG, PNG, WEBP, or GIF image, or an MP4, WEBM, or MOV video")

    url = storage.upload_file(data, content_type, folder=f"{folder}/{access.business_id}")
    media_type = MediaType.VIDEO if content_type in storage.ALLOWED_VIDEO_TYPES else MediaType.IMAGE
    return url, media_type
