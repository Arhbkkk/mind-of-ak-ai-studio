from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/tmp/mind-of-ak-uploads"))
MAX_UPLOAD_MB = max(1, int(os.getenv("MAX_UPLOAD_MB", "250")))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="Mind of AK AI Studio", version="0.1.0")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/")
async def home() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "service": "Mind of AK AI Studio", "ffmpeg_available": shutil.which("ffmpeg") is not None, "max_upload_mb": MAX_UPLOAD_MB}


@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)) -> dict:
    original_name = Path(file.filename or "video").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported video format. Use MP4, MOV, M4V, WEBM, or MKV.")

    destination = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    total = 0
    try:
        with destination.open("wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail=f"File exceeds the {MAX_UPLOAD_MB} MB upload limit.")
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    return {"ok": True, "message": "Upload received. Editing and export are not implemented yet.", "filename": original_name, "stored_as": destination.name, "size_bytes": total}
