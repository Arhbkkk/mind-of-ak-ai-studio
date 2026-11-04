from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config

UPLOAD_PART_SIZE = 8 * 1024 * 1024
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


def begin_upload(filename: str, content_type: str) -> dict[str, Any]:
    suffix = Path(filename or "video.mp4").suffix.lower()
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
    client().complete_multipart_upload(
        Bucket=os.environ["R2_BUCKET"], Key=key, UploadId=upload_id,
        MultipartUpload={"Parts": normalized},
    )
    return download_object(key, destination)


def abort_upload(key: str, upload_id: str) -> None:
    _validate_key(key)
    client().abort_multipart_upload(Bucket=os.environ["R2_BUCKET"], Key=key, UploadId=upload_id)


def download_object(key: str, destination: Path) -> int:
    _validate_key(key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    client().download_file(os.environ["R2_BUCKET"], key, str(destination))
    return destination.stat().st_size


def ensure_local(stored_name: str, destination: Path) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}\.(mp4|mov|m4v|webm|mkv)", stored_name):
        raise ValueError("Invalid uploaded file reference.")
    if not destination.is_file() and configured():
        download_object(f"temporary/{stored_name}", destination)
    return destination


def _validate_key(key: str) -> None:
    if not re.fullmatch(r"temporary/[a-f0-9]{32}\.(mp4|mov|m4v|webm|mkv)", key):
        raise ValueError("Invalid temporary object key.")
