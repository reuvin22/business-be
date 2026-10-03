"""File uploads to Cloudflare R2.

R2 works like Amazon S3, so we talk to it with boto3 (the S3 library).
Each file gets a random name, so a URL never changes what it points to, and
browsers and Cloudflare can cache it forever.

Two buckets:
  - R2_BUCKET (public): product photos and videos, logos, chat photos, return policy PDFs.
  - R2_PRIVATE_BUCKET (no public access): permits, IDs, certificates, legal documents. They are saved as
    "private:<key>" and opened with a signed link that expires after a few minutes (see signed_url), which the
    API gives only to the business's team and platform admins.

Files are deleted from R2 when what uses them is removed (delete_removed, delete_folder).
"""

import logging
import uuid

import boto3
import httpx
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, status

from app.core.config import settings
from app.schemas.base import PRIVATE_FILE_PREFIX

logger = logging.getLogger(__name__)

# What we accept, and the file extension each type gets
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}
ALLOWED_VIDEO_TYPES = {
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
}
ALLOWED_TYPES = ALLOWED_IMAGE_TYPES | ALLOWED_VIDEO_TYPES
ALLOWED_DOCUMENT_TYPES = {"application/pdf": "pdf"}
EXTENSIONS = ALLOWED_TYPES | ALLOWED_DOCUMENT_TYPES
MAX_FILE_BYTES = 25 * 1024 * 1024  # 25 MB, for each file (image or video)

_client = None


def _account_id() -> str:
    """R2_ACCOUNT_ID, also when the whole S3 API address was pasted instead,
    e.g. "https://abc123.r2.cloudflarestorage.com/business" -> "abc123"."""
    value = settings.r2_account_id.strip().removeprefix("https://").removeprefix("http://")
    return value.split("/")[0].split(".")[0]


def _get_client():
    """The R2 connection, created the first time it is needed.
    Values are trimmed: a space or line break copied along with a key breaks every upload."""
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=f"https://{_account_id()}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.r2_access_key_id.strip(),
            aws_secret_access_key=settings.r2_secret_access_key.strip(),
            region_name="auto",
        )
    return _client


def _bucket() -> str:
    return settings.r2_bucket.strip()


def _private_bucket() -> str:
    return settings.r2_private_bucket.strip()


def private_configured() -> bool:
    return settings.r2_configured and bool(_private_bucket())


SIGNED_LINK_SECONDS = 300  # how long a link to a private file works


def health() -> dict:
    """For /api/health/r2: checks each R2 setting and tries to reach the bucket. Never shows the keys."""
    account_id = _account_id()
    public_url = settings.r2_public_url.strip()
    problems = []
    if not settings.r2_configured:
        missing = [name for name in ("account_id", "access_key_id", "secret_access_key", "bucket", "public_url")
                   if not getattr(settings, f"r2_{name}").strip()]
        problems.append(f"Missing: {', '.join('R2_' + name.upper() for name in missing)}")
    if settings.r2_account_id and not (len(account_id) == 32 and all(c in "0123456789abcdef" for c in account_id.lower())):
        problems.append("R2_ACCOUNT_ID should be the 32-character Account ID from the R2 overview page")
    if settings.r2_access_key_id and len(settings.r2_access_key_id.strip()) != 32:
        problems.append("R2_ACCESS_KEY_ID should be 32 characters (the Access Key ID of an R2 API token, not the token value)")
    if settings.r2_secret_access_key and len(settings.r2_secret_access_key.strip()) != 64:
        problems.append("R2_SECRET_ACCESS_KEY should be 64 characters (the Secret Access Key of the same R2 API token)")
    if public_url and (not public_url.startswith("https://") or "r2.cloudflarestorage.com" in public_url):
        problems.append("R2_PUBLIC_URL should be the bucket's public address, e.g. https://pub-xxxx.r2.dev")

    connection = "not tried"
    if settings.r2_configured:
        try:
            _get_client().list_objects_v2(Bucket=_bucket(), MaxKeys=1)
            connection = "ok"
        except ClientError as error:
            connection = f"refused: {error.response.get('Error', {}).get('Code', 'Unknown')}"
        except Exception as error:
            connection = f"failed: {type(error).__name__}"
        if connection != "ok":
            problems.append(f"Could not open the bucket ({connection})")

    public = _check_public_url(public_url) if connection == "ok" and public_url else "not tried"
    if public not in ("ok", "not tried"):
        problems.append(public)

    return {
        "status": "ok" if not problems else "error",
        "bucket": _bucket(),
        "public_url": public_url,
        "connection": connection,
        "public_url_check": "ok" if public == "ok" else public,
        "problems": problems,
    }


HEALTH_KEY = "health-check.txt"  # always the same file, so checking again adds nothing


def _check_public_url(public_url: str) -> str:
    """Writes a tiny file to the bucket and reads it back through R2_PUBLIC_URL: the uploads only show
    in the app when that address really serves THIS bucket (each bucket has its own pub-....r2.dev)."""
    marker = uuid.uuid4().hex
    try:
        _get_client().put_object(Bucket=_bucket(), Key=HEALTH_KEY, Body=marker.encode(), ContentType="text/plain", CacheControl="no-store")
    except Exception as error:
        return f"Could not write a test file to the bucket ({type(error).__name__})"
    try:
        response = httpx.get(f"{public_url.rstrip('/')}/{HEALTH_KEY}", timeout=15, headers={"Cache-Control": "no-cache"})
    except httpx.HTTPError as error:
        return f"R2_PUBLIC_URL could not be reached ({type(error).__name__})"
    if response.status_code == 200 and response.text.strip() == marker:
        return "ok"
    return (
        f"R2_PUBLIC_URL does not show the files of the bucket '{_bucket()}' (it answered HTTP {response.status_code}). "
        "In Cloudflare: R2 > bucket '" + _bucket() + "' > Settings > Public Development URL: turn it on and copy that "
        "exact address into R2_PUBLIC_URL (each bucket has its own)."
    )


def upload_file(data: bytes, content_type: str, folder: str) -> str:
    """Saves the image or video in R2 and returns its public URL.

    folder: where it goes inside the bucket, e.g. "product_img/abc123".
    """
    key = f"{folder}/{uuid.uuid4().hex}.{EXTENSIONS[content_type]}"
    try:
        _get_client().put_object(
            Bucket=_bucket(),
            Key=key,
            Body=data,
            ContentType=content_type,
            ContentDisposition="inline",  # shown in the browser (a PDF opens in the viewer, not as a download)
            CacheControl="public, max-age=31536000, immutable",  # the name is unique, so it never changes
        )
    except ClientError as error:
        # R2 answered with an error, e.g. NoSuchBucket (wrong R2_BUCKET) or AccessDenied / InvalidAccessKeyId (keys)
        code = error.response.get("Error", {}).get("Code", "Unknown")
        logger.exception("R2 refused the upload (%s)", code)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"File storage refused the upload ({code}). Check the R2 settings on the server.",
        ) from error
    except BotoCoreError as error:
        # R2 could not be reached at all, e.g. a wrong R2_ACCOUNT_ID
        logger.exception("Could not reach R2")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach file storage ({type(error).__name__}). Check the R2 settings on the server.",
        ) from error
    except Exception as error:
        # Anything else, e.g. a bad R2 address (ValueError) - name it so the setting can be found
        logger.exception("Upload to R2 failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Upload to file storage failed ({type(error).__name__}). Check the R2 settings on the server.",
        ) from error
    return f"{settings.r2_public_url.rstrip('/')}/{key}"


# ---- Private files -----------------------------------------------------------------------------


def upload_private_file(data: bytes, content_type: str, folder: str) -> str:
    """Saves the file in the private bucket. Returns "private:<key>" (not a link: see signed_url)."""
    if not private_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Private documents are not set up yet (R2_PRIVATE_BUCKET is missing on the server)",
        )
    key = f"{folder}/{uuid.uuid4().hex}.{EXTENSIONS[content_type]}"
    try:
        _get_client().put_object(
            Bucket=_private_bucket(),
            Key=key,
            Body=data,
            ContentType=content_type,
            ContentDisposition="inline",
            CacheControl="private, no-store",  # never kept by shared caches
        )
    except (ClientError, BotoCoreError) as error:
        logger.exception("Upload to the private bucket failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"File storage refused the upload ({type(error).__name__}). Check R2_PRIVATE_BUCKET on the server.",
        ) from error
    return PRIVATE_FILE_PREFIX + key


def private_key(ref: str) -> str:
    return ref.removeprefix(PRIVATE_FILE_PREFIX)


def signed_url(ref: str) -> str:
    """A link to a private file that works for SIGNED_LINK_SECONDS. Check who is asking BEFORE calling this."""
    if not private_configured():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Private documents are not set up yet")
    return _get_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _private_bucket(), "Key": private_key(ref)},
        ExpiresIn=SIGNED_LINK_SECONDS,
    )


# ---- Deleting files ----------------------------------------------------------------------------


def _locate(url: str) -> tuple[str, str] | None:
    """(bucket, key) of a file SIRIS stored, or None for anything else (e.g. a link to another website)."""
    if url.startswith(PRIVATE_FILE_PREFIX):
        return (_private_bucket(), private_key(url)) if private_configured() else None
    public = settings.r2_public_url.strip().rstrip("/") + "/"
    if settings.r2_configured and url.startswith(public):
        return _bucket(), url.removeprefix(public)
    return None


def delete_file(url: str) -> None:
    """Deletes a stored file. Never fails what the user was doing: a problem is only logged."""
    found = _locate(url) if url else None
    if found is None:
        return
    try:
        _get_client().delete_object(Bucket=found[0], Key=found[1])
    except Exception:  # noqa: BLE001 - deleting is a clean-up: never break the request
        logger.exception("Could not delete %s from R2", found[1])


def delete_removed(before: list[str], after: list[str]) -> None:
    """Deletes the files that were in `before` but are no longer in `after` (e.g. a replaced logo)."""
    for url in set(filter(None, before)) - set(filter(None, after)):
        delete_file(url)


def delete_folder(folder: str, private: bool = False) -> None:
    """Deletes every file under a folder, e.g. product_img/<businessId> when the business is deleted."""
    bucket = _private_bucket() if private else _bucket()
    if not settings.r2_configured or not bucket:
        return
    try:
        client = _get_client()
        for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=f"{folder.rstrip('/')}/"):
            keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            if keys:
                client.delete_objects(Bucket=bucket, Delete={"Objects": keys, "Quiet": True})
    except Exception:  # noqa: BLE001
        logger.exception("Could not delete the folder %s from R2", folder)

