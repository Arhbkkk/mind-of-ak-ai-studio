from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/tmp/mind-of-ak-uploads"))
EXPORT_DIR = Path(os.getenv("EXPORT_DIR", "/tmp/mind-of-ak-exports"))
MAX_UPLOAD_MB = max(1, int(os.getenv("MAX_UPLOAD_MB", "50")))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_SOURCE_DURATION_SECONDS = max(30, int(os.getenv("MAX_SOURCE_DURATION_SECONDS", "180")))
TEMP_FILE_MAX_AGE_SECONDS = max(3600, int(os.getenv("TEMP_FILE_MAX_AGE_SECONDS", "43200")))
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def cleanup_old_files() -> None:
    """Remove stale temporary media so repeated jobs cannot fill the instance disk."""
    import time

    cutoff = time.time() - TEMP_FILE_MAX_AGE_SECONDS
    for folder in (UPLOAD_DIR, EXPORT_DIR):
        try:
            for path in folder.iterdir():
                try:
                    if path.is_file() and path.stat().st_mtime < cutoff:
                        path.unlink(missing_ok=True)
                except OSError:
                    continue
        except OSError:
            continue


cleanup_old_files()

app = FastAPI(title="Mind of AK AI Studio", version="0.2.0")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def safe_upload(name: str) -> Path:
    # Only accept generated storage names, never arbitrary paths from a request.
    if Path(name).name != name or not re.fullmatch(r"[a-f0-9]{32}\.(mp4|mov|m4v|webm|mkv)", name):
        raise HTTPException(status_code=400, detail="Invalid uploaded file reference.")
    path = UPLOAD_DIR / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Uploaded source was not found. It may have expired after a host restart.")
    return path


def _run_command_sync(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


async def run_command(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    # Keep CPU-heavy FFmpeg/FFprobe work off the ASGI event loop so /api/health
    # and other requests can still respond while media is being processed.
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_run_command_sync, args, timeout),
            timeout=timeout + 2,
        )
    except (subprocess.TimeoutExpired, asyncio.TimeoutError) as exc:
        raise HTTPException(status_code=408, detail="Processing took too long for this hosting instance. Try a shorter or smaller source video.") from exc


@app.get("/")
async def home() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "service": "Mind of AK AI Studio",
        "ffmpeg_available": shutil.which("ffmpeg") is not None,
        "ffprobe_available": shutil.which("ffprobe") is not None,
        "max_upload_mb": MAX_UPLOAD_MB,
        "max_source_duration_seconds": MAX_SOURCE_DURATION_SECONDS,
        "pipeline_version": "0.3.0",
    }


@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)) -> dict:
    original_name = Path(file.filename or "video").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported video format. Use MP4, MOV, M4V, WEBM, or MKV.")
    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        raise HTTPException(status_code=503, detail="Video processing tools are unavailable on this server.")

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

    # Verify the upload is a readable video, rather than trusting its filename.
    probe = await run_command([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,r_frame_rate,duration",
        "-show_entries", "format=duration,format_name", "-of", "json", str(destination)
    ], timeout=30)
    if probe.returncode != 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=415, detail="The uploaded file could not be read as a valid video.")
    try:
        metadata = json.loads(probe.stdout)
    except json.JSONDecodeError:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="Could not read video metadata.")
    streams = metadata.get("streams", [])
    if not streams:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=415, detail="No video stream was found in this file.")
    stream = streams[0]
    duration = float(stream.get("duration") or metadata.get("format", {}).get("duration") or 0)
    if duration <= 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=415, detail="Could not determine the video duration.")
    if duration > MAX_SOURCE_DURATION_SECONDS:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=413,
            detail=f"This free-hosting build accepts videos up to {MAX_SOURCE_DURATION_SECONDS} seconds. Trim the source and try again."
        )
    cleanup_old_files()
    return {
        "ok": True,
        "message": "Video uploaded and validated.",
        "filename": original_name,
        "stored_as": destination.name,
        "size_bytes": total,
        "duration_seconds": round(duration, 3),
        "width": stream.get("width"),
        "height": stream.get("height"),
        "video_codec": stream.get("codec_name"),
        "frame_rate": stream.get("r_frame_rate"),
    }


@app.get("/api/analyze/{stored_name}")
async def analyze_video(stored_name: str) -> dict:
    source = safe_upload(stored_name)
    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        raise HTTPException(status_code=503, detail="FFmpeg and FFprobe are required.")
    probe = await run_command([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(source)
    ], timeout=30)
    if probe.returncode != 0:
        raise HTTPException(status_code=422, detail="Could not analyse this video.")
    data = json.loads(probe.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    duration = float(data.get("format", {}).get("duration") or 0)
    if duration > MAX_SOURCE_DURATION_SECONDS:
        raise HTTPException(
            status_code=413,
            detail=f"Scene analysis is limited to {MAX_SOURCE_DURATION_SECONDS} seconds on this hosting plan."
        )
    # Scene-change candidates are detected by FFmpeg. This is signal analysis, not AI semantic understanding.
    scene_result = await run_command([
        "ffmpeg", "-hide_banner", "-threads", "1", "-filter_threads", "1",
        "-i", str(source), "-vf", "select='gt(scene,0.35)',showinfo",
        "-an", "-f", "null", "-"
    ], timeout=120)
    times = []
    if scene_result.returncode in (0, 1):
        for match in re.finditer(r"pts_time:([0-9]+(?:\.[0-9]+)?)", scene_result.stderr):
            value = float(match.group(1))
            if 0 < value < duration and (not times or value - times[-1] >= 0.5):
                times.append(round(value, 2))
    return {
        "ok": True,
        "filename": source.name,
        "duration_seconds": round(duration, 2),
        "width": video.get("width"),
        "height": video.get("height"),
        "video_codec": video.get("codec_name"),
        "frame_rate": video.get("r_frame_rate"),
        "audio_present": bool(audio),
        "audio_codec": audio.get("codec_name"),
        "scene_change_candidates": times[:100],
        "scene_detection_note": "Scene candidates are based on visual change, not AI understanding of story or meaning.",
    }


@app.post("/api/export")
async def export_video(
    stored_name: str = Form(...),
    preset: Literal["original", "vertical", "square"] = Form("original"),
    quality: Literal["high", "balanced", "small"] = Form("high"),
    start_seconds: float = Form(0),
    end_seconds: float = Form(0),
) -> dict:
    source = safe_upload(stored_name)
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise HTTPException(status_code=503, detail="FFmpeg and FFprobe are required.")
    probe = await run_command([
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(source)
    ], timeout=20)
    try:
        duration = float(probe.stdout.strip())
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Could not determine source duration.")
    if duration <= 0:
        raise HTTPException(status_code=422, detail="Invalid source duration.")
    if start_seconds < 0 or end_seconds < 0 or start_seconds >= duration:
        raise HTTPException(status_code=422, detail="Start time must be within the source video.")
    effective_end = end_seconds if end_seconds > 0 else duration
    if effective_end > duration or effective_end <= start_seconds:
        raise HTTPException(status_code=422, detail="End time must be after start time and no later than the source duration.")
    if effective_end - start_seconds > 300:
        raise HTTPException(status_code=413, detail="This starter export supports up to 5 minutes per render. Shorten the clip and retry.")

    output_name = f"ak_export_{uuid.uuid4().hex}.mp4"
    output = EXPORT_DIR / output_name
    filters = {
        "original": "scale='min(1920,iw)':-2:force_original_aspect_ratio=decrease",
        "vertical": "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
        "square": "scale=1080:1080:force_original_aspect_ratio=decrease,pad=1080:1080:(ow-iw)/2:(oh-ih)/2",
    }
    crf = {"high": "18", "balanced": "22", "small": "27"}[quality]
    preset_speed = "veryfast" if quality == "small" else "fast"
    command = [
        "ffmpeg", "-y", "-hide_banner", "-threads", "1", "-filter_threads", "1",
        "-filter_complex_threads", "1", "-ss", str(start_seconds), "-i", str(source),
        "-t", str(effective_end - start_seconds), "-vf", filters[preset],
        "-c:v", "libx264", "-threads", "1", "-preset", "veryfast", "-crf", crf,
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(output)
    ]
    result = await run_command(command, timeout=240)
    if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        output.unlink(missing_ok=True)
        detail = (result.stderr or "Unknown FFmpeg error")[-1200:]
        raise HTTPException(status_code=422, detail=f"Export failed: {detail}")
    cleanup_old_files()
    return {
        "ok": True,
        "filename": output_name,
        "download_url": f"/api/download/{output_name}",
        "size_bytes": output.stat().st_size,
        "duration_seconds": round(effective_end - start_seconds, 2),
        "preset": preset,
        "quality": quality,
        "message": "Basic FFmpeg export completed. This is not yet an AI-directed edit.",
    }


@app.get("/api/download/{filename}")
async def download_export(filename: str) -> FileResponse:
    if Path(filename).name != filename or not re.fullmatch(r"ak_export_[a-f0-9]{32}\.mp4", filename):
        raise HTTPException(status_code=400, detail="Invalid export reference.")
    path = EXPORT_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Export not found. It may have expired after a host restart.")
    return FileResponse(path, media_type="video/mp4", filename="mind-of-ak-export.mp4")
