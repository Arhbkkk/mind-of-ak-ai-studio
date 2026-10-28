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

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.validation import compare_script_to_transcript, validate_subtitles

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/tmp/mind-of-ak-uploads"))
EXPORT_DIR = Path(os.getenv("EXPORT_DIR", "/tmp/mind-of-ak-exports"))
MAX_UPLOAD_MB = max(1, int(os.getenv("MAX_UPLOAD_MB", "2048")))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_SOURCE_DURATION_SECONDS = max(30, int(os.getenv("MAX_SOURCE_DURATION_SECONDS", "300")))
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

app = FastAPI(title="Mind of AK AI Studio", version="0.4.0")
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
        "pipeline_version": "0.4.0",
        "validation_endpoint": "/api/validate",
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
        {"name": "duration", "status": "PASS" if 45 <= duration <= 300 else "WARNING", "detail": f"Source duration is {duration:.3f} seconds; target is 45–300 seconds."},
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
    if effective_end - start_seconds > 300:
        raise HTTPException(status_code=413, detail="This starter export supports up to 5 minutes per render. Shorten the clip and retry.")

    clip_duration = effective_end - start_seconds
    if not 0 <= fade_seconds <= 3:
        raise HTTPException(status_code=422, detail="Fade duration must be between 0 and 3 seconds.")
    if fade_seconds * 2 > clip_duration:
        raise HTTPException(status_code=422, detail="Fade-in and fade-out together cannot exceed the clip duration.")
    if not 0 <= audio_volume <= 2:
        raise HTTPException(status_code=422, detail="Audio volume must be between 0 and 2.")

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

    # Render instances on the free 512 MiB plan can be OOM-killed by 1080p/4K
    # blur graphs. Cap the actual render canvas to 720p-class dimensions while
    # keeping the selected aspect ratio; higher resolution presets are advisory
    # only on this constrained host.
    max_render_edge = 640
    if max(target_width, target_height) > max_render_edge:
        ratio = max_render_edge / max(target_width, target_height)
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
        command.extend(["-filter_complex", complex_filters + "[vout]", "-map", "[vout]"])
    elif framing == "blur" and preset == "original":
        command.extend(["-vf", ",".join([f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease", "pad=ceil(iw/2)*2:ceil(ih/2)*2", looks[color_style]] + ([f"fade=t=in:st=0:d={fade_seconds}", f"fade=t=out:st={max(0, clip_duration - fade_seconds)}:d={fade_seconds}"] if fade_seconds > 0 else []))])
    else:
        command.extend(["-vf", ",".join(video_filters + ["pad=ceil(iw/2)*2:ceil(ih/2)*2"])])
    command.extend([
        "-af", ",".join(audio_filters),
        "-c:v", "libx264", "-threads", "1", "-preset", "ultrafast", "-crf", crf,
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(output)
    ])
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
        "framing": framing,
        "resolution": resolution,
        "output_width": target_width,
        "output_height": target_height,
        "quality": quality,
        "color_style": color_style,
        "fade_seconds": fade_seconds,
        "audio_volume": audio_volume,
        "message": "Creative export completed with framing, color look, optional fades, and audio volume. AI-directed editing is not included yet.",
    }



# In-process render jobs keep long FFmpeg work out of the browser's initial HTTP request.
# For multi-instance/production reliability, replace this dictionary with a durable queue.
_EXPORT_JOBS: dict[str, dict] = {}

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
) -> dict:
    # The worker runs FFmpeg with a 240-second timeout. Clear any in-memory job
    # that has exceeded a generous 5-minute deadline, otherwise a killed worker
    # can leave exports permanently locked until the next service restart.
    now = time.time()
    for stale_id, stale_job in list(_EXPORT_JOBS.items()):
        if stale_job.get("status") in ("queued", "running"):
            started_at = stale_job.get("started_at", stale_job.get("created_at", now))
            if now - started_at > 300:
                stale_job.update(status="failed", progress=0,
                                 error="Export timed out or its worker stopped. Please start a new export.")
                print(f"EXPORT_JOB_STALE id={stale_id} age_seconds={int(now - started_at)}", flush=True)
    # This single-process service has no external queue; reject only active renders.
    if any(job.get("status") in ("queued", "running") for job in _EXPORT_JOBS.values()):
        raise HTTPException(status_code=429, detail="Another export is still running. Wait for it to finish before starting another render.")
    # Fail fast for missing sources; the render itself runs asynchronously.
    safe_upload(stored_name)
    job_id = uuid.uuid4().hex
    _EXPORT_JOBS[job_id] = {"status": "queued", "progress": 0, "message": "Render queued.", "created_at": time.time(), "started_at": time.time()}

    async def run_job() -> None:
        _EXPORT_JOBS[job_id].update(status="running", progress=1, message="FFmpeg render started.")
        print(f"EXPORT_JOB_START id={job_id} preset={preset} framing={framing} resolution={resolution}", flush=True)
        try:
            result = await _render_export_now(
                stored_name=stored_name,
                preset=preset,
                framing=framing,
                resolution=resolution,
                quality=quality,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                color_style=color_style,
                fade_seconds=fade_seconds,
                audio_volume=audio_volume,
            )
            _EXPORT_JOBS[job_id].update(status="completed", progress=100, message="Export completed.", result=result)
            print(f"EXPORT_JOB_COMPLETE id={job_id} bytes={result.get('size_bytes')}", flush=True)
        except HTTPException as exc:
            _EXPORT_JOBS[job_id].update(status="failed", progress=0, error=str(exc.detail))
            print(f"EXPORT_JOB_FAILED id={job_id} status={exc.status_code} error={exc.detail}", flush=True)
        except Exception as exc:
            _EXPORT_JOBS[job_id].update(status="failed", progress=0, error=f"Unexpected render error: {type(exc).__name__}: {exc}")
            print(f"EXPORT_JOB_CRASH id={job_id} error={type(exc).__name__}: {exc}", flush=True)

    asyncio.create_task(run_job())
    return {"ok": True, "job_id": job_id, "status": "queued", "status_url": f"/api/export-status/{job_id}"}


@app.get("/api/export-status/{job_id}")
async def export_status(job_id: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise HTTPException(status_code=400, detail="Invalid render job ID.")
    job = _EXPORT_JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Render job not found. The service may have restarted; please submit the export again.")
    response = {"ok": True, "job_id": job_id, "status": job["status"], "progress": job.get("progress", 0), "message": job.get("message", "")}
    if job["status"] == "completed":
        response["result"] = job["result"]
    elif job["status"] == "failed":
        response["error"] = job.get("error", "Unknown render failure.")
    return response


@app.get("/api/download/{filename}")
async def download_export(filename: str) -> FileResponse:
    if Path(filename).name != filename or not re.fullmatch(r"ak_export_[a-f0-9]{32}\.mp4", filename):
        raise HTTPException(status_code=400, detail="Invalid export reference.")
    path = EXPORT_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Export not found. It may have expired after a host restart.")
    return FileResponse(path, media_type="video/mp4", filename="mind-of-ak-export.mp4")
