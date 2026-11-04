"""Provider-neutral object storage and owner-scoped project manifests.

Local storage is for development only. Configure R2_* or S3_* variables for durable storage.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

PROJECT_CHANNELS = {"mind-of-ak", "kids-stories", "mind-relax-bgm"}
PROJECT_SCHEMA_VERSION = 1
PROJECT_ID_RE = re.compile(r"^[a-f0-9]{32}$")


class StorageError(RuntimeError):
    pass


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
    def list(self, prefix: str) -> list[str]: ...


def _validate_key(key: str) -> str:
    if not key or key.startswith("/") or "\\" in key or any(p in ("", ".", "..") for p in key.split("/")):
        raise ValueError("Invalid object key.")
    return key


class LocalObjectStore:
    """Atomic local adapter for development; hosted local disks may be ephemeral."""
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / _validate_key(key)).resolve()
        if self.root not in path.parents:
            raise ValueError("Object key escapes storage root.")
        return path

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError as exc:
            raise StorageError("Stored object was not found.") from exc

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def list(self, prefix: str) -> list[str]:
        base = self._path(prefix.rstrip("/"))
        if base.is_file():
            return [base.relative_to(self.root).as_posix()]
        if not base.exists():
            return []
        return sorted(path.relative_to(self.root).as_posix() for path in base.rglob("*") if path.is_file())


class S3ObjectStore:
    """S3-compatible adapter for Cloudflare R2, AWS S3, and compatible providers."""
    def __init__(self, bucket: str, endpoint_url: str | None = None, region: str | None = None,
                 access_key: str | None = None, secret_key: str | None = None):
        try:
            import boto3
        except ImportError as exc:
            raise StorageError("S3 storage requires boto3.") from exc
        from botocore.config import Config
        access = access_key or os.getenv("R2_ACCESS_KEY_ID") or os.getenv("S3_ACCESS_KEY_ID")
        secret = secret_key or os.getenv("R2_SECRET_ACCESS_KEY") or os.getenv("S3_SECRET_ACCESS_KEY")
        if bool(access) != bool(secret):
            raise StorageError("Both object-storage access key and secret key are required.")
        kwargs: dict[str, Any] = {"region_name": region or "us-east-1", "config": Config(signature_version="s3v4")}
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        if access and secret:
            kwargs.update(aws_access_key_id=access, aws_secret_access_key=secret)
        self.client = boto3.client("s3", **kwargs)
        self.bucket = bucket

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.client.put_object(Bucket=self.bucket, Key=_validate_key(key), Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=_validate_key(key))["Body"].read()
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if code in {"NoSuchKey", "404", "NotFound"}:
                raise StorageError("Stored object was not found.") from exc
            raise StorageError("Object storage read failed.") from exc

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=_validate_key(key))
        except Exception as exc:
            raise StorageError("Object storage delete failed.") from exc

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=_validate_key(key))
            return True
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise StorageError("Object storage lookup failed.") from exc

    def list(self, prefix: str) -> list[str]:
        safe_prefix = _validate_key(prefix.rstrip("/")) + "/"
        try:
            paginator = self.client.get_paginator("list_objects_v2")
            return sorted(item["Key"] for page in paginator.paginate(Bucket=self.bucket, Prefix=safe_prefix)
                          for item in page.get("Contents", []))
        except Exception as exc:
            raise StorageError("Object storage listing failed.") from exc


def build_object_store() -> ObjectStore:
    r2_bucket = os.getenv("R2_BUCKET", "").strip()
    if r2_bucket:
        account = os.getenv("R2_ACCOUNT_ID", "").strip()
        if not account:
            raise StorageError("R2_ACCOUNT_ID is required when R2_BUCKET is configured.")
        return S3ObjectStore(
            r2_bucket,
            endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
            region="auto",
        )
    bucket = os.getenv("S3_BUCKET", "").strip()
    if bucket:
        return S3ObjectStore(bucket, os.getenv("S3_ENDPOINT_URL") or None, os.getenv("S3_REGION") or None)
    return LocalObjectStore(os.getenv("PROJECT_STORAGE_DIR", "/tmp/mind-of-ak-projects"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectRepository:
    """Versioned project manifests in a fixed owner namespace."""
    def __init__(self, store: ObjectStore, owner_id: str = "owner"):
        if not owner_id or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", owner_id):
            raise ValueError("Invalid owner identifier.")
        self.store, self.owner_id = store, owner_id

    def _key(self, project_id: str) -> str:
        if not isinstance(project_id, str) or not PROJECT_ID_RE.fullmatch(project_id):
            raise ValueError("Invalid project ID.")
        return f"owners/{self.owner_id}/projects/{project_id}/manifest.json"

    def create(self, title: str, channel: str, settings: dict[str, Any] | None = None) -> dict[str, Any]:
        title = title.strip() if isinstance(title, str) else ""
        if not title or len(title) > 120:
            raise ValueError("Project title must contain 1 to 120 characters.")
        if channel not in PROJECT_CHANNELS:
            raise ValueError("Unknown creator channel.")
        if settings is not None and not isinstance(settings, dict):
            raise ValueError("Project settings must be an object.")
        now = _utc_now()
        project = {
            "schema_version": PROJECT_SCHEMA_VERSION, "id": uuid.uuid4().hex,
            "owner_id": self.owner_id, "title": title, "channel": channel,
            "created_at": now, "updated_at": now, "status": "draft",
            "settings": settings or {}, "assets": [], "timeline": {"tracks": []},
            "script": "", "subtitles": "", "story_parts": [],
        }
        self.save(project)
        return project

    def save(self, project: dict[str, Any]) -> None:
        if not isinstance(project, dict) or project.get("owner_id") != self.owner_id:
            raise ValueError("Project owner does not match this workspace.")
        key = self._key(project.get("id"))
        if project.get("schema_version") != PROJECT_SCHEMA_VERSION:
            raise ValueError("Unsupported project schema version.")
        if project.get("channel") not in PROJECT_CHANNELS:
            raise ValueError("Unknown creator channel.")
        if not isinstance(project.get("assets"), list) or not isinstance(project.get("timeline"), dict):
            raise ValueError("Project assets and timeline have invalid shapes.")
        encoded = json.dumps(project, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > 2 * 1024 * 1024:
            raise ValueError("Project manifest exceeds the 2 MB limit.")
        project["updated_at"] = _utc_now()
        encoded = json.dumps(project, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.store.put(key, encoded, "application/json")

    def get(self, project_id: str) -> dict[str, Any]:
        try:
            project = json.loads(self.store.get(self._key(project_id)).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StorageError("Project manifest is corrupted.") from exc
        if project.get("owner_id") != self.owner_id:
            raise StorageError("Project owner mismatch.")
        return project

    def list(self) -> list[dict[str, Any]]:
        prefix = f"owners/{self.owner_id}/projects"
        projects = []
        for key in self.store.list(prefix):
            if not key.endswith("/manifest.json"):
                continue
            project_id = key.rsplit("/", 2)[-2]
            try:
                projects.append(self.get(project_id))
            except (ValueError, StorageError):
                continue
        return sorted(projects, key=lambda item: item.get("updated_at", ""), reverse=True)

    def delete(self, project_id: str) -> None:
        self.store.delete(self._key(project_id))
