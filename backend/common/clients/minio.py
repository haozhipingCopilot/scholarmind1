"""
MinIO client helpers: upload bytes, download to a temp file.
All calls are synchronous (minio SDK is sync); wrap with asyncio.to_thread() in async contexts.
"""
import io
import tempfile
import os

from minio import Minio
from minio.error import S3Error

from common.config import settings
from common.logging import logger


def _get_client() -> Minio:
    return Minio(
        settings.MINIO_ENDPOINT,
        access_key=settings.MINIO_ACCESS_KEY,
        secret_key=settings.MINIO_SECRET_KEY,
        secure=settings.MINIO_SECURE,
    )


def ensure_bucket(bucket: str) -> None:
    """Create bucket if it does not exist."""
    client = _get_client()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
        logger.info(f"[minio] created bucket: {bucket}")


def upload_bytes(bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Upload raw bytes to MinIO. Returns the key."""
    client = _get_client()
    client.put_object(
        bucket,
        key,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    return key


def download_to_tempfile(bucket: str, key: str, suffix: str = ".tmp") -> str:
    """
    Download an object from MinIO to a local temp file.
    Returns the temp file path. Caller is responsible for deleting it.
    """
    client = _get_client()
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        client.fget_object(bucket, key, tmp_path)
    except S3Error as e:
        os.unlink(tmp_path)
        raise
    return tmp_path
