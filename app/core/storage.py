"""Image uploads to Cloudflare R2.

R2 works like Amazon S3, so we talk to it with boto3 (the S3 library).
Each file gets a random name, so a URL never changes what it points to, and
browsers and Cloudflare can cache it forever.
"""

import uuid

import boto3

from app.core.config import settings

# What we accept, and the file extension each type gets
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB

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


def upload_image(data: bytes, content_type: str, folder: str) -> str:
    """Saves the image in R2 and returns its public URL.

    folder: where it goes inside the bucket, e.g. "businesses/abc123/images".
    """
    key = f"{folder}/{uuid.uuid4().hex}.{ALLOWED_IMAGE_TYPES[content_type]}"
    _get_client().put_object(
        Bucket=settings.r2_bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
        CacheControl="public, max-age=31536000, immutable",  # the name is unique, so it never changes
    )
    return f"{settings.r2_public_url.rstrip('/')}/{key}"
