"""MinIO object storage helper.

Required env vars (set via MINIO_* in .env):
  MINIO_ENDPOINT        — host:port of MinIO server (default: minio:9000)
  MINIO_ACCESS_KEY      — access key (default: CHANGE_ME)
  MINIO_SECRET_KEY      — secret key (default: CHANGE_ME)
  MINIO_BUCKET_DOCUMENTS — bucket name for raw documents (default: chathr-documents)
  MINIO_SECURE          — use TLS (default: false)

Raw document bytes are stored here. Never store raw content in the DB or audit logs.
"""
import io

from app.core.config import settings


def _client():
    from minio import Minio  # type: ignore[import-untyped]

    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def ensure_bucket_exists(bucket: str) -> None:
    """Create the bucket if it does not exist."""
    client = _client()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def get_bytes(bucket: str, object_key: str) -> bytes:
    """Download object from MinIO and return raw bytes."""
    client = _client()
    response = client.get_object(bucket, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def put_bytes(
    bucket: str,
    object_key: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> None:
    """Upload bytes to MinIO. Creates the bucket if needed."""
    client = _client()
    ensure_bucket_exists(bucket)
    client.put_object(
        bucket,
        object_key,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
