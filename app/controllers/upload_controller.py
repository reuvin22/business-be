"""Uploading product photos and videos, and the business logo and cover, to Cloudflare R2."""

from fastapi import HTTPException, UploadFile, status

from app.controllers.crud import bad_request, forbidden, not_found
from app.core import rate_limit, storage
from app.core.config import settings
from app.dependencies.business_access import BusinessAccess
from app.schemas.base import PRIVATE_FILE_PREFIX
from app.schemas.enums import MediaType, Permission


def detect_file_type(data: bytes) -> str | None:
    """The real type of an image or video, from its first bytes (we don't trust the name or the browser)."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
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
# Products can have videos too; the logo, cover, and chat photos must be images.
# Chat photos: any member may send them (sending the message itself checks who may write where).
UPLOAD_KINDS = {
    "product": ("product_img", Permission.MANAGE_PRODUCTS, storage.ALLOWED_TYPES),
    "business": ("business_img", Permission.EDIT_BUSINESS, storage.ALLOWED_IMAGE_TYPES),
    "chat": ("chat_img", None, storage.ALLOWED_IMAGE_TYPES),
    "policy": ("policy_docs", Permission.EDIT_BUSINESS, storage.ALLOWED_DOCUMENT_TYPES),  # e.g. the return policy PDF
    # Permits, IDs, certificates: in the PRIVATE bucket (see storage.signed_url)
    "document": ("private_docs", Permission.EDIT_BUSINESS, storage.ALLOWED_IMAGE_TYPES | storage.ALLOWED_DOCUMENT_TYPES),
    # A buyer's proof of payment (e.g. a bank transfer screenshot): private too
    "proof": ("payment_proofs", Permission.PLACE_ORDERS, storage.ALLOWED_IMAGE_TYPES | storage.ALLOWED_DOCUMENT_TYPES),
}
PRIVATE_KINDS = {"document", "proof"}

# How much one business may upload per day (stops a script from filling the storage and the bill)
DAILY_UPLOAD_BYTES = 1024 * 1024 * 1024


def upload_business_file(access: BusinessAccess, file: UploadFile, kind: str = "product") -> tuple[str, MediaType]:
    """Checks the file and stores it in the folder for its kind. Returns its URL and whether it is an image or video.

    kind: "product" (product photos and videos), "business" (logo, cover), or "chat" (photos sent in messages)."""
    if kind not in UPLOAD_KINDS:
        raise bad_request(f"kind must be one of: {', '.join(UPLOAD_KINDS)}")
    folder, permission, allowed = UPLOAD_KINDS[kind]
    if permission is not None and not access.can(permission):
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
    if not rate_limit.use_quota(f"upload:{access.business_id}", len(data), DAILY_UPLOAD_BYTES, 24 * 60 * 60):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Your business has uploaded a lot today (1 GB). Please try again tomorrow.",
        )
    content_type = detect_file_type(data)
    if content_type not in allowed:
        if allowed is storage.ALLOWED_DOCUMENT_TYPES:
            raise bad_request("Please choose a PDF file")
        if kind in PRIVATE_KINDS:
            raise bad_request("Please choose a PDF, or a JPG, PNG, WEBP, or GIF image")
        if allowed is storage.ALLOWED_IMAGE_TYPES:
            raise bad_request("Please choose a JPG, PNG, WEBP, or GIF image")
        raise bad_request("Please choose a JPG, PNG, WEBP, or GIF image, or an MP4, WEBM, or MOV video")

    if kind in PRIVATE_KINDS:
        url = storage.upload_private_file(data, content_type, folder=f"{folder}/{access.business_id}")
    else:
        url = storage.upload_file(data, content_type, folder=f"{folder}/{access.business_id}")
    media_type = (
        MediaType.VIDEO
        if content_type in storage.ALLOWED_VIDEO_TYPES
        else MediaType.DOCUMENT
        if content_type in storage.ALLOWED_DOCUMENT_TYPES
        else MediaType.IMAGE
    )
    return url, media_type


def open_private_file(access: BusinessAccess, ref: str) -> str:
    """A short-lived link to one of this business's private files (its team may see them all)."""
    key = storage.private_key(ref)
    owned = any(key.startswith(f"{UPLOAD_KINDS[kind][0]}/{access.business_id}/") for kind in PRIVATE_KINDS)
    if not ref.startswith(PRIVATE_FILE_PREFIX) or not owned or ".." in key:
        raise not_found("File")
    return storage.signed_url(ref)

