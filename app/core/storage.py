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


def _get_client():
    """The R2 connection, created the first time it is needed."""
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
        )
    return _client


def upload_file(data: bytes, content_type: str, folder: str) -> str:
    """Saves the image or video in R2 and returns its public URL.

    folder: where it goes inside the bucket, e.g. "product_img/abc123".
    """
    key = f"{folder}/{uuid.uuid4().hex}.{ALLOWED_TYPES[content_type]}"
    try:
        _get_client().put_object(
            Bucket=settings.r2_bucket,
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
    return f"{settings.r2_public_url.rstrip('/')}/{key}"
