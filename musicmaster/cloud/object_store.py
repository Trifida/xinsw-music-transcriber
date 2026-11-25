# -*- coding: utf-8 -*-
"""Private Neon S3-compatible object storage for source audio and score artifacts."""
from __future__ import annotations

import os
from typing import BinaryIO


class ObjectStoreError(RuntimeError):
    """Object storage is unavailable or rejected an operation."""


class S3ObjectStore:
    def __init__(
        self,
        *,
        bucket: str | None = None,
        endpoint_url: str | None = None,
        region: str | None = None,
    ) -> None:
        self.bucket = (bucket or os.environ.get("MUSICMASTER_BUCKET", "xinsw-music-jobs")).strip()
        self.endpoint_url = (endpoint_url or os.environ.get("AWS_ENDPOINT_URL_S3", "")).strip()
        self.region = (region or os.environ.get("AWS_REGION", "")).strip()
        access_key = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
        secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
        if not all((self.bucket, self.endpoint_url, self.region, access_key, secret_key)):
            raise ValueError(
                "Object storage requires MUSICMASTER_BUCKET and AWS_ENDPOINT_URL_S3, "
                "AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY."
            )
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover - depends on deployment extra
            raise ObjectStoreError("Cloud jobs require boto3.") from exc
        self._client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            region_name=self.region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                connect_timeout=8,
                read_timeout=60,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    @staticmethod
    def _key(key: str) -> str:
        value = str(key or "").lstrip("/")
        if not value or "\x00" in value or any(part == ".." for part in value.split("/")):
            raise ValueError("Invalid object key.")
        return value

    def upload_fileobj(
        self,
        fileobj: BinaryIO,
        key: str,
        *,
        content_type: str = "application/octet-stream",
    ) -> None:
        safe_key = self._key(key)
        try:
            fileobj.seek(0)
            self._client.upload_fileobj(
                fileobj,
                self.bucket,
                safe_key,
                ExtraArgs={"ContentType": content_type or "application/octet-stream"},
            )
        except Exception as exc:  # noqa: BLE001
            raise ObjectStoreError(f"Object upload failed: {type(exc).__name__}") from None

    def presigned_download(self, key: str, *, expires_seconds: int = 900) -> str:
        return self._presign(
            "get_object", {"Bucket": self.bucket, "Key": self._key(key)}, expires_seconds
        )

    def presigned_upload(
        self,
        key: str,
        *,
        content_type: str = "application/octet-stream",
        expires_seconds: int = 900,
    ) -> str:
        return self._presign(
            "put_object",
            {
                "Bucket": self.bucket,
                "Key": self._key(key),
                "ContentType": content_type or "application/octet-stream",
            },
            expires_seconds,
        )

    def _presign(self, operation: str, params: dict, expires_seconds: int) -> str:
        expiry = max(60, min(int(expires_seconds), 3600))
        try:
            return self._client.generate_presigned_url(
                operation, Params=params, ExpiresIn=expiry
            )
        except Exception as exc:  # noqa: BLE001
            raise ObjectStoreError(f"Could not create object URL: {type(exc).__name__}") from None

    def head(self, key: str) -> dict:
        try:
            result = self._client.head_object(Bucket=self.bucket, Key=self._key(key))
            return {
                "size_bytes": int(result.get("ContentLength") or 0),
                "content_type": result.get("ContentType") or "application/octet-stream",
            }
        except Exception as exc:  # noqa: BLE001
            raise ObjectStoreError(f"Object check failed: {type(exc).__name__}") from None

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self.bucket, Key=self._key(key))
        except Exception as exc:  # noqa: BLE001
            raise ObjectStoreError(f"Object deletion failed: {type(exc).__name__}") from None
