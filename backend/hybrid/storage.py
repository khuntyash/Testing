from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO


class LocalArtifactStore:
    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or os.getenv("LOCAL_ARTIFACT_ROOT", "./artifacts")).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def write_bytes(self, key: str, content: bytes) -> Path:
        path = (self.root / key).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def read_bytes(self, key: str) -> bytes:
        return (self.root / key).resolve().read_bytes()


class S3ArtifactStore:
    """R2/S3-compatible object storage adapter."""

    def __init__(self) -> None:
        try:
            import boto3  # type: ignore
        except Exception as exc:
            raise RuntimeError("boto3 is not installed") from exc

        bucket = os.getenv("S3_BUCKET", "").strip()
        endpoint = os.getenv("S3_ENDPOINT_URL", "").strip()
        region = os.getenv("S3_REGION", "auto").strip() or "auto"
        if not bucket:
            raise RuntimeError("S3_BUCKET is required for s3 storage backend")
        self.bucket = bucket
        self.client = boto3.client(  # type: ignore[attr-defined]
            "s3",
            endpoint_url=endpoint or None,
            aws_access_key_id=os.getenv("S3_ACCESS_KEY_ID", "").strip() or None,
            aws_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY", "").strip() or None,
            region_name=region,
        )

    def upload_file(self, key: str, local_path: str) -> None:
        self.client.upload_file(local_path, self.bucket, key)

    def upload_bytes(self, key: str, content: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=content)

    def download_to_file(self, key: str, local_path: str) -> None:
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, key, local_path)

    def open_stream(self, key: str) -> BinaryIO:
        obj = self.client.get_object(Bucket=self.bucket, Key=key)
        return obj["Body"]

    def presigned_get(self, key: str, expires_sec: int = 3600) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=max(60, int(expires_sec)),
        )

