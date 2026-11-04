from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config

UPLOAD_PART_SIZE = 8 * 1024 * 1024
MAX_DIRECT_UPLOAD_MB = max(1, int(os.getenv('MAX_DIRECT_UPLOAD_MB', '2048')))
MAX_DIRECT_UPLOAD_BYTES = MAX_DIRECT_UPLOAD_MB * 1024 * 1024
ALLOWED_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}


def configured() -> bool:
    return all(os.getenv(key) for key in (
        "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"
    ))


def client():
    if not configured():
        raise RuntimeError("R2 storage is not configured on the backend.")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def begin_upload(filename: str, content_type: str, size_bytes: int) -> dict[str, Any]:
    suffix = Path(filename or "video.mp4").suffix.lower()
    if size_bytes <= 0 or size_bytes > MAX_DIRECT_UPLOAD_BYTES:
        raise ValueError(f"Direct uploads must be between 1 byte and {MAX_DIRECT_UPLOAD_MB} MB.")
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError("Unsupported video format.")
    safe_name = f"{uuid.uuid4().hex}{suffix}"
    key = f"temporary/{safe_name}"
    result = client().create_multipart_upload(
        Bucket=os.environ["R2_BUCKET"],
        Key=key,
        ContentType=content_type if content_type.startswith("video/") else "application/octet-stream",
        Metadata={"lifecycle": "temporary"},
    )
    return {"stored_as": safe_name, "object_key": key, "upload_id": result["UploadId"], "part_size": UPLOAD_PART_SIZE}


def sign_part(key: str, upload_id: str, part_number: int) -> str:
    _validate_key(key)
    if not 1 <= part_number <= 10000:
        raise ValueError("Invalid multipart part number.")
    return client().generate_presigned_url(
        "upload_part",
        Params={"Bucket": os.environ["R2_BUCKET"], "Key": key, "UploadId": upload_id, "PartNumber": part_number},
        ExpiresIn=900,
        HttpMethod="PUT",
    )


def complete_upload(key: str, upload_id: str, parts: list[dict], destination: Path) -> int:
    _validate_key(key)
    if not parts or len(parts) > 10000:
        raise ValueError("Invalid multipart upload parts.")
    normalized = []
    for item in parts:
        number = int(item.get("PartNumber", 0))
        etag = str(item.get("ETag", "")).strip('"')
        if not 1 <= number <= 10000 or not etag:
            raise ValueError("Invalid multipart upload part metadata.")
        normalized.append({"PartNumber": number, "ETag": etag})
    normalized.sort(key=lambda item: item["PartNumber"])
    storage = client()
    storage.complete_multipart_upload(
        Bucket=os.environ["R2_BUCKET"], Key=key, UploadId=upload_id,
        MultipartUpload={"Parts": normalized},
    )
    head = storage.head_object(Bucket=os.environ["R2_BUCKET"], Key=key)
    size_bytes = int(head.get("ContentLength", 0))
    if size_bytes <= 0 or size_bytes > MAX_DIRECT_UPLOAD_BYTES:
        storage.delete_object(Bucket=os.environ["R2_BUCKET"], Key=key)
        raise ValueError(f"Completed upload exceeds the {MAX_DIRECT_UPLOAD_MB} MB limit.")
    return download_object(key, destination)


def abort_upload(key: str, upload_id: str) -> None:
    _validate_key(key)
    client().abort_multipart_upload(Bucket=os.environ["R2_BUCKET"], Key=key, UploadId=upload_id)


def download_object(key: str, destination: Path) -> int:
    _validate_key(key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    client().download_file(os.environ["R2_BUCKET"], key, str(destination))
    return destination.stat().st_size


def _validate_stored_name(stored_name: str) -> None:
    if not re.fullmatch(r"[a-f0-9]{32}\.(mp4|mov|m4v|webm|mkv)", stored_name):
        raise ValueError("Invalid uploaded file reference.")


def _validate_project_id(project_id: str) -> None:
    if not re.fullmatch(r"[a-f0-9]{32}", project_id):
        raise ValueError("Invalid project reference.")


def promote_source(stored_name: str, project_id: str) -> str:
    """Move a temporary upload into a project-owned, non-expiring R2 prefix."""
    _validate_stored_name(stored_name)
    _validate_project_id(project_id)
    storage = client()
    temporary_key = f"temporary/{stored_name}"
    target_key = f"owners/owner/projects/{project_id}/media/{stored_name}"
    source_key = temporary_key
    try:
        storage.head_object(Bucket=os.environ["R2_BUCKET"], Key=temporary_key)
    except Exception:
        source_key = find_project_source_key(stored_name) or ""
        if not source_key:
            raise FileNotFoundError("Source media is no longer available in temporary or saved project storage.")
    if source_key != target_key:
        storage.copy_object(
            Bucket=os.environ["R2_BUCKET"],
            Key=target_key,
            CopySource={"Bucket": os.environ["R2_BUCKET"], "Key": source_key},
            MetadataDirective="COPY",
        )
        if source_key == temporary_key:
            storage.delete_object(Bucket=os.environ["R2_BUCKET"], Key=source_key)
    return target_key


def find_project_source_key(stored_name: str) -> str | None:
    _validate_stored_name(stored_name)
    prefix = "owners/owner/projects/"
    paginator = client().get_paginator("list_objects_v2")
    suffix = f"/media/{stored_name}"
    for page in paginator.paginate(Bucket=os.environ["R2_BUCKET"], Prefix=prefix):
        for item in page.get("Contents", []):
            key = item.get("Key", "")
            if key.endswith(suffix):
                return key
    return None


def delete_project_source(project_id: str, stored_name: str) -> None:
    _validate_project_id(project_id)
    _validate_stored_name(stored_name)
    key = f"owners/owner/projects/{project_id}/media/{stored_name}"
    client().delete_object(Bucket=os.environ["R2_BUCKET"], Key=key)


def presign_project_source(project_id: str, stored_name: str, expires_in: int = 900) -> str:
    _validate_project_id(project_id)
    _validate_stored_name(stored_name)
    key = f"owners/owner/projects/{project_id}/media/{stored_name}"
    return client().generate_presigned_url(
        "get_object",
        Params={"Bucket": os.environ["R2_BUCKET"], "Key": key},
        ExpiresIn=max(60, min(int(expires_in), 3600)),
        HttpMethod="GET",
    )


def ensure_local(stored_name: str, destination: Path) -> Path:
    _validate_stored_name(stored_name)
    if not destination.is_file() and configured():
        storage = client()
        temporary_key = f"temporary/{stored_name}"
        try:
            storage.head_object(Bucket=os.environ["R2_BUCKET"], Key=temporary_key)
            download_object(temporary_key, destination)
        except Exception:
            project_key = find_project_source_key(stored_name)
            if not project_key:
                raise FileNotFoundError("Source media was not found in temporary or saved project storage.")
            download_object(project_key, destination)
    return destination


def _validate_key(key: str) -> None:
    if not re.fullmatch(r"temporary/[a-f0-9]{32}\.(mp4|mov|m4v|webm|mkv)", key):
        raise ValueError("Invalid temporary object key.")


def save_export(filename: str, source: Path) -> str:
    """Persist a completed MP4 under a non-expiring saved/ key."""
    if not re.fullmatch(r"ak_export_[a-f0-9]{32}\.mp4", filename):
        raise ValueError("Invalid export filename.")
    key = f"saved/{filename}"
    client().upload_file(
        str(source), os.environ["R2_BUCKET"], key,
        ExtraArgs={"ContentType": "video/mp4", "Metadata": {"lifecycle": "saved"}},
    )
    return key


def presign_saved_export(filename: str, expires_in: int = 900) -> str:
    if not re.fullmatch(r"ak_export_[a-f0-9]{32}\.mp4", filename):
        raise ValueError("Invalid export filename.")
    return client().generate_presigned_url(
        "get_object",
        Params={"Bucket": os.environ["R2_BUCKET"], "Key": f"saved/{filename}"},
        ExpiresIn=max(60, min(int(expires_in), 3600)),
        HttpMethod="GET",
    )
