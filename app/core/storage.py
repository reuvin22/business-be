"""Image and video uploads to Cloudflare R2.

R2 works like Amazon S3, so we talk to it with boto3 (the S3 library).
Each file gets a random name, so a URL never changes what it points to, and
browsers and Cloudflare can cache it forever.
"""

import logging
import uuid

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, status

from app.core.config import settings

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


def status() -> dict:
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

    return {
        "status": "ok" if not problems else "error",
        "bucket": _bucket(),
        "public_url": public_url,
        "connection": connection,
        "problems": problems,
    }


def upload_file(data: bytes, content_type: str, folder: str) -> str:
    """Saves the image or video in R2 and returns its public URL.

    folder: where it goes inside the bucket, e.g. "product_img/abc123".
    """
    key = f"{folder}/{uuid.uuid4().hex}.{ALLOWED_TYPES[content_type]}"
    try:
        _get_client().put_object(
            Bucket=_bucket(),
            Key=key,
            Body=data,
            ContentType=content_type,
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
