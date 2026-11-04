from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Literal

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from app.validation import compare_script_to_transcript, validate_subtitles, parse_srt, validate_timeline_segments
from app.subtitles import build_subtitle_filter
from app import job_store
from app.auth import install_owner_gate
from app.storage import ProjectRepository, StorageError, build_object_store
from app import r2_storage

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/tmp/mind-of-ak-uploads"))
EXPORT_DIR = Path(os.getenv("EXPORT_DIR", "/tmp/mind-of-ak-exports"))
MAX_UPLOAD_MB = max(0, int(os.getenv("MAX_UPLOAD_MB", "0")))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_SOURCE_DURATION_SECONDS = max(30, int(os.getenv("MAX_SOURCE_DURATION_SECONDS", "600")))
MAX_RENDER_EDGE = max(640, int(os.getenv("MAX_RENDER_EDGE", "640")))
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

app = FastAPI(title="Mind of AK AI Studio", version="0.5.0")
install_owner_gate(app)
project_repository = ProjectRepository(build_object_store())
job_store.init_db()
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def safe_upload(name: str) -> Path:
    # Only accept generated storage names, never arbitrary paths from a request.
    if Path(name).name != name or not re.fullmatch(r"[a-f0-9]{32}\.(mp4|mov|m4v|webm|mkv)", name):
        raise HTTPException(status_code=400, detail="Invalid uploaded file reference.")
    path = UPLOAD_DIR / name
    if not path.is_file() and r2_storage.configured():
        try:
            r2_storage.ensure_local(name, path)
        except Exception as exc:
            raise HTTPException(status_code=404, detail="Uploaded source was not found in temporary R2 storage.") from exc
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
        "upload_limit_enabled": MAX_UPLOAD_MB > 0,
        "max_source_duration_seconds": MAX_SOURCE_DURATION_SECONDS,
        "max_render_edge": MAX_RENDER_EDGE,
        "pipeline_version": "0.5.0",
        "validation_endpoint": "/api/validate",
        "project_storage": "r2" if os.getenv("R2_BUCKET") else ("s3" if os.getenv("S3_BUCKET") else "local_ephemeral"),
    }


@app.get("/api/projects")
async def list_projects() -> dict:
    projects = project_repository.list()
    return {"projects": [
        {key: project.get(key) for key in ("id", "title", "channel", "status", "created_at", "updated_at")}
        for project in projects
    ]}


@app.post("/api/projects")
async def create_project(payload: dict = Body(...)) -> dict:
    try:
        project = project_repository.create(
            payload.get("title", ""),
            payload.get("channel", ""),
            payload.get("settings"),
        )
    except (ValueError, StorageError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "project": project}


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str) -> dict:
    try:
        return {"project": project_repository.get(project_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/api/projects/{project_id}")
async def update_project(project_id: str, payload: dict = Body(...)) -> dict:
    try:
        project = project_repository.get(project_id)
        allowed = {"title", "channel", "status", "settings", "assets", "timeline", "script", "subtitles", "story_parts", "export_settings", "render_history"}
        for key in allowed:
            if key in payload:
                project[key] = payload[key]
        if not isinstance(project.get("title"), str) or not project["title"].strip() or len(project["title"]) > 120:
            raise ValueError("Project title must contain 1 to 120 characters.")
        if project.get("status") not in {"draft", "ready", "rendering", "completed", "failed"}:
            raise ValueError("Invalid project status.")
        if not isinstance(project.get("settings"), dict) or not isinstance(project.get("assets"), list):
            raise ValueError("Project settings and assets must be objects/lists.")
        if not isinstance(project.get("timeline"), dict) or not isinstance(project.get("story_parts"), list):
            raise ValueError("Project timeline and story parts have invalid shapes.")
        if not isinstance(project.get("script", ""), str) or not isinstance(project.get("subtitles", ""), str):
            raise ValueError("Project script and subtitles must be text.")
        project_repository.save(project)
        return {"ok": True, "project": project}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str) -> dict:
    try:
        project_repository.delete(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "deleted": project_id}


@app.get("/api/storage/status")
async def storage_status() -> dict:
    enabled = r2_storage.configured()
    return {
        "enabled": enabled,
        "provider": "Cloudflare R2" if enabled else None,
        "upload_mode": "direct-multipart" if enabled else "backend-proxy",
    }


@app.post("/api/storage/multipart/initiate")
async def storage_multipart_initiate(request: Request) -> dict:
    if not r2_storage.configured():
        raise HTTPException(status_code=503, detail="R2 storage is not configured.")
    try:
        data = await request.json()
        result = r2_storage.begin_upload(
            str(data.get("filename", "")),
            str(data.get("content_type", "application/octet-stream")),
            int(data.get("size_bytes", 0)),
        )
        return {"ok": True, **result}
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Could not start direct storage upload.") from exc


@app.post("/api/storage/multipart/sign-part")
async def storage_multipart_sign_part(request: Request) -> dict:
    try:
        data = await request.json()
        url = r2_storage.sign_part(
            str(data.get("object_key", "")),
            str(data.get("upload_id", "")),
            int(data.get("part_number", 0)),
        )
        return {"ok": True, "url": url}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Could not sign upload part.") from exc


@app.post("/api/storage/multipart/complete")
async def storage_multipart_complete(request: Request) -> dict:
    try:
        data = await request.json()
        name = str(data.get("stored_as", ""))
        if not re.fullmatch(r"[a-f0-9]{32}\.(mp4|mov|m4v|webm|mkv)", name):
            raise ValueError("Invalid uploaded file reference.")
        key = str(data.get("object_key", ""))
        if key != f"temporary/{name}":
            raise ValueError("Upload object key does not match the generated file reference.")
        destination = UPLOAD_DIR / name
        total = r2_storage.complete_upload(
            key, str(data.get("upload_id", "")), data.get("parts", []), destination
        )
        probe = await run_command([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,r_frame_rate,duration",
            "-show_entries", "format=duration,format_name", "-of", "json", str(destination)
        ], timeout=45)
        if probe.returncode != 0:
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=415, detail="The uploaded file could not be read as a valid video.")
        metadata = json.loads(probe.stdout)
        streams = metadata.get("streams", [])
        if not streams:
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=415, detail="No video stream was found in this file.")
        stream = streams[0]
        duration = float(stream.get("duration") or metadata.get("format", {}).get("duration") or 0)
        if duration <= 0 or duration > MAX_SOURCE_DURATION_SECONDS:
            destination.unlink(missing_ok=True)
            raise HTTPException(
                status_code=413,
                detail=f"Video duration must be between 1 and {MAX_SOURCE_DURATION_SECONDS} seconds.",
            )
        return {
            "ok": True,
            "message": "Video uploaded to R2 and validated.",
            "stored_as": name,
            "size_bytes": total,
            "duration_seconds": round(duration, 3),
            "width": stream.get("width"),
            "height": stream.get("height"),
            "video_codec": stream.get("codec_name"),
            "frame_rate": stream.get("r_frame_rate"),
            "storage": "Cloudflare R2",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not complete or validate the R2 upload. Retry the upload.") from exc


@app.post("/api/storage/multipart/abort")
async def storage_multipart_abort(request: Request) -> dict:
    try:
        data = await request.json()
        r2_storage.abort_upload(str(data.get("object_key", "")), str(data.get("upload_id", "")))
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not abort the incomplete upload.") from exc


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
                if MAX_UPLOAD_MB > 0 and total > MAX_UPLOAD_BYTES:
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



@app.post("/api/validate")
async def validate_media(stored_name: str = Form(...), script: str = Form(""), srt_file: UploadFile | None = File(None), transcript_text: str = Form("")) -> dict:
    """Deterministic checks; unperformed AI checks remain explicitly unverified."""
    source = safe_upload(stored_name)
    probe = await run_command(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(source)], timeout=30)
    if probe.returncode != 0:
        raise HTTPException(status_code=422, detail="Could not inspect source media.")
    try:
        metadata = json.loads(probe.stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Could not parse source media metadata.") from exc
    streams = metadata.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(metadata.get("format", {}).get("duration") or 0)
    if not video or duration <= 0:
        raise HTTPException(status_code=422, detail="Source must contain a readable video stream and valid duration.")
    checks = [
        {"name": "video_stream", "status": "PASS", "detail": "FFprobe found a readable video stream."},
        {"name": "duration", "status": "PASS" if 45 <= duration <= 600 else "WARNING", "detail": f"Source duration is {duration:.3f} seconds; target is 45–300 seconds."},
        {"name": "audio_stream", "status": "PASS" if audio else "FAIL", "detail": "Audio stream detected." if audio else "No audio stream detected."},
        {"name": "image_narration_semantics", "status": "NOT_VERIFIED", "detail": "Image relevance has not been checked by a vision model or human reviewer."},
        {"name": "rendered_output", "status": "NOT_VERIFIED", "detail": "This endpoint validates source media only, not a rendered output."},
    ]
    subtitle_report = None
    if srt_file is not None and srt_file.filename:
        if not srt_file.filename.lower().endswith(".srt"):
            raise HTTPException(status_code=415, detail="Subtitle upload must be an .srt file.")
        raw = await srt_file.read()
        await srt_file.close()
        if len(raw) > 5 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="SRT file exceeds 5 MB.")
        try:
            subtitle_report = validate_subtitles(raw.decode("utf-8-sig"), duration)
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=422, detail="SRT must be UTF-8 encoded.") from exc
        checks.extend({"name": "subtitle_" + item["name"], "status": item["status"], "detail": item["detail"]} for item in subtitle_report.get("checks", []))
    else:
        checks.append({"name": "subtitle_file", "status": "NOT_VERIFIED", "detail": "No SRT file supplied."})
    transcript_report = compare_script_to_transcript(script, transcript_text)
    checks.append({"name": "script_audio_comparison", "status": transcript_report["status"], "detail": transcript_report["detail"]})
    if script.strip() and not transcript_text.strip():
        checks.append({"name": "speech_recognition", "status": "NOT_VERIFIED", "detail": "ASR is not integrated; this endpoint does not transcribe audio."})
    statuses = [item["status"] for item in checks]
    overall = "FAIL" if "FAIL" in statuses else ("WARNING" if "WARNING" in statuses or "NOT_VERIFIED" in statuses else "PASS")
    return {"ok": True, "overall_status": overall, "export_gate": "BLOCKED" if overall in ("FAIL", "WARNING") else "ELIGIBLE_FOR_REVIEW", "source": {"duration_seconds": round(duration, 3), "width": video.get("width"), "height": video.get("height"), "video_codec": video.get("codec_name"), "audio_present": bool(audio), "audio_codec": audio.get("codec_name") if audio else None}, "checks": checks, "subtitles": subtitle_report, "script_comparison": transcript_report, "important_limit": "No claim of perfect validation: audio transcription, semantic image matching, and post-render audiovisual review remain unverified without dedicated checkers or human review."}

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


async def _render_export_now(
    stored_name: str = Form(...),
    preset: Literal["original", "landscape", "vertical", "square", "social"] = Form("original"),
    framing: Literal["fit", "fill", "blur"] = Form("blur"),
    resolution: Literal["720p", "1080p", "1440p", "4k"] = Form("1080p"),
    quality: Literal["high", "balanced", "small"] = Form("high"),
    start_seconds: float = Form(0),
    end_seconds: float = Form(0),
    color_style: Literal["natural", "cinematic", "warm", "mono"] = Form("natural"),
    fade_seconds: float = Form(0),
    audio_volume: float = Form(1),
    subtitle_srt: str = Form(""),
    subtitle_size: int = Form(36),
    subtitle_position: Literal["bottom", "middle", "top"] = Form("bottom"),
    subtitle_color: Literal["white", "yellow"] = Form("white"),
    persist_export: bool = True,
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
    # The browser displays source duration rounded to milliseconds. Permit that
    # tiny display-rounding difference, then clamp to the exact FFprobe duration.
    if effective_end > duration + 0.05 or effective_end <= start_seconds:
        raise HTTPException(status_code=422, detail="End time must be after start time and no later than the source duration.")
    effective_end = min(effective_end, duration)
    if effective_end - start_seconds > 600:
        raise HTTPException(status_code=413, detail="This build supports up to 10 minutes per render. Shorten the clip and retry.")

    clip_duration = effective_end - start_seconds
    subtitle_file = None
    subtitle_filter = None
    if subtitle_srt.strip():
        if not 20 <= subtitle_size <= 64:
            raise HTTPException(status_code=422, detail="Subtitle font size must be between 20 and 64.")
        if len(subtitle_srt.encode("utf-8")) > 1_000_000:
            raise HTTPException(status_code=413, detail="Subtitle file must be smaller than 1 MB.")
        try:
            subtitle_cues = parse_srt(subtitle_srt)
            if len(subtitle_cues) > 2000:
                raise ValueError("Subtitle files may contain at most 2,000 cues.")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid SRT subtitles: {exc}") from exc
        subtitle_check = validate_subtitles(subtitle_srt, clip_duration)
        if subtitle_check["status"] == "FAIL":
            raise HTTPException(status_code=422, detail="Subtitle timestamps must fit inside the selected export clip. Use clip-relative timestamps starting at 00:00:00,000.")
    if not 0 <= fade_seconds <= 3:
        raise HTTPException(status_code=422, detail="Fade duration must be between 0 and 3 seconds.")
    if fade_seconds * 2 > clip_duration:
        raise HTTPException(status_code=422, detail="Fade-in and fade-out together cannot exceed the clip duration.")
    if not 0 <= audio_volume <= 2:
        raise HTTPException(status_code=422, detail="Audio volume must be between 0 and 2.")

    if subtitle_srt.strip():
        subtitle_file = EXPORT_DIR / f"ak_subtitles_{uuid.uuid4().hex}.srt"
        subtitle_file.write_text(subtitle_srt, encoding="utf-8")
        subtitle_filter = build_subtitle_filter(subtitle_file, subtitle_size, subtitle_position, subtitle_color)

    output_name = f"ak_export_{uuid.uuid4().hex}.mp4"
    output = EXPORT_DIR / output_name
    # Dimensions are fixed even numbers for reliable H.264/yuv420p playback.
    # "original" uses FFprobe dimensions and caps the long edge at the selected resolution.
    if preset == "original":
        source_probe = await run_command([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json", str(source)
        ], timeout=20)
        try:
            source_stream = json.loads(source_probe.stdout)["streams"][0]
            source_width, source_height = int(source_stream["width"]), int(source_stream["height"])
        except (ValueError, KeyError, IndexError, json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=422, detail="Could not determine source video dimensions.") from exc
        long_edge = {"720p": 1280, "1080p": 1920, "1440p": 2560, "4k": 3840}[resolution]
        scale = min(1.0, long_edge / max(source_width, source_height))
        target_width = max(2, int(source_width * scale) // 2 * 2)
        target_height = max(2, int(source_height * scale) // 2 * 2)
    else:
        dimensions = {
            "720p": {"landscape": (1280, 720), "vertical": (720, 1280), "square": (720, 720), "social": (720, 900)},
            "1080p": {"landscape": (1920, 1080), "vertical": (1080, 1920), "square": (1080, 1080), "social": (1080, 1350)},
            "1440p": {"landscape": (2560, 1440), "vertical": (1440, 2560), "square": (1440, 1440), "social": (1440, 1800)},
            "4k": {"landscape": (3840, 2160), "vertical": (2160, 3840), "square": (2160, 2160), "social": (1728, 2160)},
        }
        target_width, target_height = dimensions[resolution][preset]

    # Keep low-memory deployments safe by default, but let larger hosts opt in
    # to higher output dimensions through MAX_RENDER_EDGE.
    if max(target_width, target_height) > MAX_RENDER_EDGE:
        ratio = MAX_RENDER_EDGE / max(target_width, target_height)
        target_width = max(2, int(target_width * ratio) // 2 * 2)
        target_height = max(2, int(target_height * ratio) // 2 * 2)

    if framing == "fill":
        base_filters = [f"scale={target_width}:{target_height}:force_original_aspect_ratio=increase", f"crop={target_width}:{target_height}"]
    elif framing == "blur":
        # Duplicate the source: blurred, cropped background + aspect-preserving foreground.
        base_filters = []
    else:
        base_filters = [f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease", f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:color=black"]

    looks = {
        "natural": "eq=contrast=1.02:saturation=1.03:brightness=0",
        "cinematic": "eq=contrast=1.12:saturation=0.88:brightness=-0.015",
        "warm": "eq=contrast=1.04:saturation=1.12:brightness=0.01,colorbalance=rs=0.04:gs=0.01:bs=-0.03",
        "mono": "hue=s=0,eq=contrast=1.08",
    }
    video_filters = base_filters + [looks[color_style]]
    if subtitle_filter:
        video_filters.append(subtitle_filter)
    if fade_seconds > 0:
        video_filters.append(f"fade=t=in:st=0:d={fade_seconds}")
        video_filters.append(f"fade=t=out:st={max(0, clip_duration - fade_seconds)}:d={fade_seconds}")

    audio_filters = [f"volume={audio_volume}"]
    if fade_seconds > 0:
        audio_filters.extend([f"afade=t=in:st=0:d={fade_seconds}", f"afade=t=out:st={max(0, clip_duration - fade_seconds)}:d={fade_seconds}"])
    crf = {"high": "18", "balanced": "22", "small": "27"}[quality]
    command = [
        "ffmpeg", "-y", "-hide_banner", "-threads", "1", "-filter_threads", "1",
        "-filter_complex_threads", "1", "-ss", str(start_seconds), "-i", str(source),
        "-t", str(clip_duration),
    ]
    if framing == "blur" and preset != "original":
        complex_filters = (
            f"[0:v]split=2[bgsrc][fgsrc];"
            f"[bgsrc]scale={target_width}:{target_height}:force_original_aspect_ratio=increase,"
            f"crop={target_width}:{target_height},boxblur=24:12[bg];"
            f"[fgsrc]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,{looks[color_style]}"
        )
        if fade_seconds > 0:
            complex_filters += f",fade=t=in:st=0:d={fade_seconds},fade=t=out:st={max(0, clip_duration - fade_seconds)}:d={fade_seconds}"
        if subtitle_filter:
            complex_filters += f",{subtitle_filter}"
        command.extend(["-filter_complex", complex_filters + "[vout]", "-map", "[vout]"])
    elif framing == "blur" and preset == "original":
        original_filters = [f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease", "pad=ceil(iw/2)*2:ceil(ih/2)*2", looks[color_style]] + ([f"fade=t=in:st=0:d={fade_seconds}", f"fade=t=out:st={max(0, clip_duration - fade_seconds)}:d={fade_seconds}"] if fade_seconds > 0 else [])
        if subtitle_filter:
            original_filters.append(subtitle_filter)
        command.extend(["-vf", ",".join(original_filters)])
    else:
        command.extend(["-vf", ",".join(video_filters + ["pad=ceil(iw/2)*2:ceil(ih/2)*2"])])
    command.extend([
        "-af", ",".join(audio_filters),
        "-c:v", "libx264", "-threads", "1", "-preset", "ultrafast", "-crf", crf,
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(output)
    ])
    try:
        result = await run_command(command, timeout=240)
    finally:
        if subtitle_file is not None:
            subtitle_file.unlink(missing_ok=True)
    if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        output.unlink(missing_ok=True)
        detail = (result.stderr or "Unknown FFmpeg error")[-1200:]
        raise HTTPException(status_code=422, detail=f"Export failed: {detail}")
    durable_storage = False
    if persist_export and r2_storage.configured():
        try:
            r2_storage.save_export(output_name, output)
            durable_storage = True
        except Exception as exc:
            output.unlink(missing_ok=True)
            raise HTTPException(status_code=502, detail="Render completed but saving the export to R2 failed. The export was not marked as saved.") from exc
    cleanup_old_files()
    return {
        "ok": True,
        "filename": output_name,
        "download_url": f"/api/download/{output_name}",
        "size_bytes": output.stat().st_size,
        "duration_seconds": round(effective_end - start_seconds, 2),
        "preset": preset,
        "framing": framing,
        "resolution": resolution,
        "output_width": target_width,
        "output_height": target_height,
        "quality": quality,
        "color_style": color_style,
        "fade_seconds": fade_seconds,
        "audio_volume": audio_volume,
        "subtitles_burned_in": bool(subtitle_srt.strip()),
        "durable_storage": durable_storage,
        "message": "Export completed with framing, color look, optional fades, audio volume and optional burned-in SRT subtitles. AI-directed editing is not included yet.",
    }



def _srt_timestamp(seconds: float) -> str:
    millis = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


def _slice_srt_for_source_range(srt_text: str, source_start: float, source_end: float) -> str:
    """Clip source-relative subtitle cues and remap them to one timeline segment."""
    if not srt_text.strip():
        return ""
    output = []
    for cue in parse_srt(srt_text):
        start = max(cue["start_seconds"], source_start)
        end = min(cue["end_seconds"], source_end)
        if end <= start:
            continue
        output.append(
            f"{len(output) + 1}\n{_srt_timestamp(start - source_start)} --> "
            f"{_srt_timestamp(end - source_start)}\n{cue['text']}"
        )
    return "\n\n".join(output)


async def _render_timeline_now(
    stored_name: str,
    segments: list[dict],
    preset: str,
    framing: str,
    resolution: str,
    quality: str,
    color_style: str,
    fade_seconds: float,
    audio_volume: float,
    subtitle_srt: str,
    subtitle_size: int,
    subtitle_position: str,
    subtitle_color: str,
) -> dict:
    """Render ordered ranges from one source and concatenate their MP4 outputs."""
    source = safe_upload(stored_name)
    probe = await run_command([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(source)
    ], timeout=20)
    try:
        source_duration = float(probe.stdout.strip())
        ranges = validate_timeline_segments(segments, source_duration)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid timeline: {exc}") from exc

    parts: list[Path] = []
    concat_file = EXPORT_DIR / f"ak_concat_{uuid.uuid4().hex}.txt"
    final_name = f"ak_export_{uuid.uuid4().hex}.mp4"
    final_path = EXPORT_DIR / final_name
    completed = False
    try:
        for start, end in ranges:
            part_srt = _slice_srt_for_source_range(subtitle_srt, start, end)
            part = await _render_export_now(
                stored_name=stored_name,
                preset=preset,
                framing=framing,
                resolution=resolution,
                quality=quality,
                start_seconds=start,
                end_seconds=end,
                color_style=color_style,
                fade_seconds=fade_seconds,
                audio_volume=audio_volume,
                subtitle_srt=part_srt,
                subtitle_size=subtitle_size,
                subtitle_position=subtitle_position,
                subtitle_color=subtitle_color,
                persist_export=False,
            )
            parts.append(EXPORT_DIR / part["filename"])

        concat_file.write_text(
            "".join("file '" + str(path).replace("'", "'\\''") + "'\n" for path in parts),
            encoding="utf-8",
        )
        joined = await run_command([
            "ffmpeg", "-hide_banner", "-threads", "1", "-f", "concat",
            "-safe", "0", "-i", str(concat_file), "-c", "copy",
            "-movflags", "+faststart", "-y", str(final_path)
        ], timeout=240)
        if joined.returncode != 0 or not final_path.is_file() or final_path.stat().st_size == 0:
            raise HTTPException(status_code=422, detail="Timeline concatenation failed: " + (joined.stderr or "")[-1000:])

        verify = await run_command([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-show_entries", "stream=width,height", "-of", "json", str(final_path)
        ], timeout=20)
        if verify.returncode != 0:
            raise HTTPException(status_code=422, detail="Could not verify the timeline export.")
        metadata = json.loads(verify.stdout)
        video = next((item for item in metadata.get("streams", []) if item.get("codec_type") == "video"), {})
        duration = float(metadata.get("format", {}).get("duration") or 0)
        if duration <= 0 or not video:
            raise HTTPException(status_code=422, detail="Timeline export is missing a valid video stream.")
        durable_storage = False
        if r2_storage.configured():
            try:
                r2_storage.save_export(final_name, final_path)
                durable_storage = True
            except Exception as exc:
                raise HTTPException(status_code=502, detail="Timeline rendered but durable R2 storage failed.") from exc
        cleanup_old_files()
        completed = True
        return {
            "ok": True,
            "filename": final_name,
            "download_url": f"/api/download/{final_name}",
            "size_bytes": final_path.stat().st_size,
            "duration_seconds": round(duration, 2),
            "preset": preset,
            "framing": framing,
            "resolution": resolution,
            "output_width": video.get("width"),
            "output_height": video.get("height"),
            "quality": quality,
            "color_style": color_style,
            "timeline_clips": len(ranges),
            "subtitles_burned_in": bool(subtitle_srt.strip()),
            "durable_storage": durable_storage,
            "message": "Ordered timeline clips rendered and joined with hard cuts. Transitions and multiple source files are not supported yet.",
        }
    finally:
        concat_file.unlink(missing_ok=True)
        for part in parts:
            part.unlink(missing_ok=True)
        if not completed:
            final_path.unlink(missing_ok=True)


# Render jobs persist in SQLite; a separate worker executes FFmpeg.
@app.post("/api/export")
async def start_export(
    stored_name: str = Form(...),
    preset: Literal["original", "landscape", "vertical", "square", "social"] = Form("original"),
    framing: Literal["fit", "fill", "blur"] = Form("blur"),
    resolution: Literal["720p", "1080p", "1440p", "4k"] = Form("1080p"),
    quality: Literal["high", "balanced", "small"] = Form("high"),
    start_seconds: float = Form(0),
    end_seconds: float = Form(0),
    color_style: Literal["natural", "cinematic", "warm", "mono"] = Form("natural"),
    fade_seconds: float = Form(0),
    audio_volume: float = Form(1),
    subtitle_srt: str = Form(""),
    subtitle_size: int = Form(36),
    subtitle_position: Literal["bottom", "middle", "top"] = Form("bottom"),
    subtitle_color: Literal["white", "yellow"] = Form("white"),
    timeline_json: str = Form(""),
) -> dict:
    if not 20 <= subtitle_size <= 64:
        raise HTTPException(status_code=422, detail="Subtitle font size must be between 20 and 64.")
    if len(subtitle_srt.encode("utf-8")) > 1_000_000:
        raise HTTPException(status_code=413, detail="Subtitle file must be smaller than 1 MB.")
    if subtitle_srt.strip():
        try:
            cues = parse_srt(subtitle_srt)
            if len(cues) > 2000:
                raise ValueError("Subtitle files may contain at most 2,000 cues.")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid SRT subtitles: {exc}") from exc
    source = safe_upload(stored_name)
    timeline_segments = None
    if len(timeline_json.encode("utf-8")) > 20_000:
        raise HTTPException(status_code=413, detail="Timeline data exceeds the 20 KB limit.")
    if timeline_json.strip():
        try:
            timeline_segments = json.loads(timeline_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail="Timeline data must be valid JSON.") from exc
        probe = await run_command([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(source)
        ], timeout=20)
        try:
            validate_timeline_segments(timeline_segments, float(probe.stdout.strip()))
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=f"Invalid timeline: {exc}") from exc
    payload = {
        "stored_name": stored_name, "preset": preset, "framing": framing,
        "resolution": resolution, "quality": quality,
        "start_seconds": start_seconds, "end_seconds": end_seconds,
        "color_style": color_style, "fade_seconds": fade_seconds,
        "audio_volume": audio_volume,
        "subtitle_srt": subtitle_srt,
        "subtitle_size": subtitle_size,
        "subtitle_position": subtitle_position,
        "subtitle_color": subtitle_color,
    }
    if timeline_segments is not None:
        payload["timeline_segments"] = timeline_segments
    try:
        job_id = job_store.enqueue(payload, max_active=5)
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return {"ok": True, "job_id": job_id, "status": "queued",
            "status_url": f"/api/export-status/{job_id}"}


@app.get("/api/export-status/{job_id}")
async def export_status(job_id: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise HTTPException(status_code=400, detail="Invalid render job ID.")
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Render job not found.")
    response = {
        "ok": True, "job_id": job_id, "status": job["status"],
        "progress": job["progress"], "message": job["message"],
    }
    if job["status"] == "completed":
        response["result"] = job["result"]
    elif job["status"] == "failed":
        response["error"] = job["error"] or "Unknown render failure."
    return response


@app.get("/api/download/{filename}")
async def download_export(filename: str) -> FileResponse:
    if Path(filename).name != filename or not re.fullmatch(r"ak_export_[a-f0-9]{32}\.mp4", filename):
        raise HTTPException(status_code=400, detail="Invalid export reference.")
    if r2_storage.configured():
        try:
            url = r2_storage.presign_saved_export(filename, expires_in=900)
            return RedirectResponse(url, status_code=307)
        except Exception as exc:
            raise HTTPException(status_code=404, detail="Saved export was not found in R2.") from exc
    path = EXPORT_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Export not found. It may have expired after a host restart.")
    return FileResponse(path, media_type="video/mp4", filename="mind-of-ak-export.mp4")
