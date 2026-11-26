"""Object storage abstraction: MinIO/S3 in deployment, local filesystem for dev/tests."""

from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from app.core.config import Settings, get_settings


class StorageError(RuntimeError):
    pass


class ObjectStorage(Protocol):
    def put_file(self, key: str, path: Path, content_type: str | None = None) -> None: ...
    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None: ...
    def download(self, key: str, dest: Path) -> Path: ...
    def get_bytes(self, key: str) -> bytes: ...
    def get_range(self, key: str, start: int, end: int) -> bytes: ...
    def size(self, key: str) -> int: ...
    def delete_prefix(self, prefix: str) -> None: ...
    def healthy(self) -> bool: ...


def _safe_key(key: str) -> str:
    if key.startswith("/") or ".." in Path(key).parts:
        raise StorageError(f"unsafe key: {key}")
    return key


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / _safe_key(key)

    def put_file(self, key: str, path: Path, content_type: str | None = None) -> None:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    def download(self, key: str, dest: Path) -> Path:
        src = self._path(key)
        if not src.is_file():
            raise StorageError(f"missing object {key}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        return dest

    def get_bytes(self, key: str) -> bytes:
        src = self._path(key)
        if not src.is_file():
            raise StorageError(f"missing object {key}")
        return src.read_bytes()

    def get_range(self, key: str, start: int, end: int) -> bytes:
        with self._path(key).open("rb") as fh:
            fh.seek(start)
            return fh.read(end - start + 1)

    def size(self, key: str) -> int:
        p = self._path(key)
        if not p.is_file():
            raise StorageError(f"missing object {key}")
        return p.stat().st_size

    def delete_prefix(self, prefix: str) -> None:
        target = self._path(prefix)
        if target.is_dir():
            shutil.rmtree(target)
        elif target.is_file():
            target.unlink()

    def healthy(self) -> bool:
        return self.root.is_dir()


class S3Storage:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = settings.s3_bucket
        self.client: Any = client or boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )

    def ensure_bucket(self) -> None:
        from botocore.exceptions import ClientError

        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    def put_file(self, key: str, path: Path, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self.client.upload_file(str(path), self.bucket, _safe_key(key), ExtraArgs=extra)

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        extra = {"ContentType": content_type} if content_type else {}
        self.client.put_object(Bucket=self.bucket, Key=_safe_key(key), Body=data, **extra)

    def download(self, key: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.client.download_file(self.bucket, _safe_key(key), str(dest))
        except Exception as exc:
            raise StorageError(f"missing object {key}") from exc
        return dest

    def get_bytes(self, key: str) -> bytes:
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=_safe_key(key))
        except Exception as exc:
            raise StorageError(f"missing object {key}") from exc
        data: bytes = obj["Body"].read()
        return data

    def get_range(self, key: str, start: int, end: int) -> bytes:
        obj = self.client.get_object(
            Bucket=self.bucket, Key=_safe_key(key), Range=f"bytes={start}-{end}"
        )
        data: bytes = obj["Body"].read()
        return data

    def size(self, key: str) -> int:
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=_safe_key(key))
        except Exception as exc:
            raise StorageError(f"missing object {key}") from exc
        return int(head["ContentLength"])

    def delete_prefix(self, prefix: str) -> None:
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=_safe_key(prefix)):
            keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if keys:
                self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": keys})

    def healthy(self) -> bool:
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False


@lru_cache
def get_storage() -> ObjectStorage:
    settings = get_settings()
    if settings.storage_backend == "s3":
        s3 = S3Storage(settings)
        s3.ensure_bucket()
        return s3
    return LocalStorage(Path(settings.local_storage_path))
