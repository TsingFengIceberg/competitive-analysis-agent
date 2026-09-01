"""Pluggable durable storage adapters for knowledge ingestion artifacts.

The local filesystem remains the zero-configuration default.  Deployments can
switch to an S3-compatible object store without changing the knowledge
service's document/version contract.  Optional dependencies are imported only
when the corresponding backend is selected.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Protocol


class ObjectStore(Protocol):
    """Minimal byte-oriented object store contract used by ingestion."""

    def put_bytes(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> str:
        ...

    def get_bytes(self, key: str) -> bytes:
        ...

    def delete(self, key: str) -> None:
        ...


def _safe_key(key: str) -> str:
    raw_parts = str(key).replace("\\", "/").split("/")
    if any(part == ".." for part in raw_parts):
        raise ValueError("Invalid object key")
    value = "/".join(part for part in raw_parts if part not in {"", "."})
    if not value or len(value) > 512 or not re.fullmatch(r"[A-Za-z0-9._/@+ -]+", value):
        raise ValueError("Invalid object key")
    return value


class LocalObjectStore:
    """Atomic filesystem-backed object store for development and single-node use."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / _safe_key(key)).resolve()
        if self.root != path and self.root not in path.parents:
            raise ValueError("Object key escapes storage root")
        return path

    def put_bytes(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> str:
        del content_type
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
        return key

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        try:
            path.unlink()
        except FileNotFoundError:
            return


class S3ObjectStore:
    """S3-compatible object store adapter (requires the optional boto3 package)."""

    def __init__(self, *, bucket: str, prefix: str = "", endpoint_url: str | None = None, region: str | None = None) -> None:
        if not bucket.strip():
            raise ValueError("CI_AGENT_OBJECT_STORE_BUCKET is required for S3 storage")
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - depends on deployment extras
            raise RuntimeError("S3 object storage requires the optional boto3 dependency") from exc
        self.bucket = bucket.strip()
        self.prefix = prefix.strip("/")
        self.client = boto3.client("s3", endpoint_url=endpoint_url or None, region_name=region or None)

    def _key(self, key: str) -> str:
        safe = _safe_key(key)
        return f"{self.prefix}/{safe}" if self.prefix else safe

    def put_bytes(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> str:
        self.client.put_object(Bucket=self.bucket, Key=self._key(key), Body=data, ContentType=content_type)
        return key

    def get_bytes(self, key: str) -> bytes:
        return bytes(self.client.get_object(Bucket=self.bucket, Key=self._key(key))["Body"].read())

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(key))


def build_object_store(default_root: str | Path) -> ObjectStore:
    """Build the configured object store, defaulting to a local durable root."""
    backend = os.getenv("CI_AGENT_OBJECT_STORE", "local").strip().casefold()
    if backend in {"s3", "minio", "r2"}:
        return S3ObjectStore(
            bucket=os.getenv("CI_AGENT_OBJECT_STORE_BUCKET", ""),
            prefix=os.getenv("CI_AGENT_OBJECT_STORE_PREFIX", "knowledge"),
            endpoint_url=os.getenv("CI_AGENT_OBJECT_STORE_ENDPOINT", "") or None,
            region=os.getenv("CI_AGENT_OBJECT_STORE_REGION", "") or None,
        )
    if backend != "local":
        raise ValueError(f"Unsupported CI_AGENT_OBJECT_STORE backend: {backend}")
    return LocalObjectStore(os.getenv("CI_AGENT_OBJECT_STORE_ROOT", str(default_root)))


def qdrant_connection_options() -> dict[str, str | None]:
    """Return remote Qdrant settings without importing the Qdrant client."""
    url = os.getenv("CI_AGENT_RAG_QDRANT_URL", "").strip() or None
    api_key = os.getenv("CI_AGENT_RAG_QDRANT_API_KEY", "").strip() or None
    return {"url": url, "api_key": api_key}


__all__ = ["LocalObjectStore", "ObjectStore", "S3ObjectStore", "build_object_store", "qdrant_connection_options"]
