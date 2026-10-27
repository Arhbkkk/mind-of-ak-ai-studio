# Mind of AK AI Studio

Mind of AK AI Studio is a browser-based creator workspace being developed in stages. This repository currently contains a working upload/validation, FFmpeg scene-change analysis, and basic MP4 export foundation. It is **not yet a complete AI editor**.

## Current Phase 2 features

- Responsive dark-glass and gold interface.
- Upload video files in MP4, MOV, M4V, WEBM, or MKV format.
- Server-side file size limit via `MAX_UPLOAD_MB` (default 250 MB).
- Validate that an upload contains a readable video stream using FFprobe.
- Read duration, resolution, codec, frame rate, and audio-stream presence.
- Find visual scene-change candidates using FFmpeg's scene-change filter. This is visual-change detection, not semantic AI scene understanding.
- Export an MP4 with original, vertical 9:16, or square framing.
- Choose high, balanced, or smaller-file export quality.
- Trim a clip by start/end seconds; this starter limits each export to 5 minutes.
- Download the rendered MP4 to the user's device.
- Save an edit brief in the current browser using local storage (not sent to an AI provider).

## Not implemented yet

- AI prompt-to-edit and automatic scene-by-scene directing.
- Automatic highlight selection, beat matching, transitions, and gaming montage.
- Automatic captions/transcription, including Tamil-English code-switching.
- Tamil/English TTS, original music, sleep ambience, and kids' story narration.
- AI asset search and licensing verification, generated diagrams, puzzle drawings, or B-roll insertion.
- Natural denoise, stabilization, color grading, super-resolution/upscaling, or any guarantee of increased source detail.
- Voice Studio, Style DNA, project accounts, cloud project persistence, collaborative editing, or queued/background render jobs.

The roadmap takes inspiration from professional editing workflows (timeline control, precise trimming, audio mixing, color management, captions, proxy workflows, and export presets) without copying proprietary source code, brand assets, or protected UI designs from other products.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`.

FFmpeg and FFprobe must be installed and available on PATH. The Dockerfile installs FFmpeg, which also supplies FFprobe.

## API

- `GET /` — web interface.
- `GET /api/health` — service and media-tool status.
- `POST /api/upload` — multipart field `file`; validates the uploaded video.
- `GET /api/analyze/{stored_name}` — technical metadata and visual scene-change candidates.
- `POST /api/export` — multipart fields: `stored_name`, `preset` (`original`, `vertical`, `square`), `quality` (`high`, `balanced`, `small`), `start_seconds`, `end_seconds` (0 means source end).
- `GET /api/download/{filename}` — download a completed export.

## Environment variables

- `MAX_UPLOAD_MB`: upload limit (default 250).
- `UPLOAD_DIR`: source upload directory (default `/tmp/mind-of-ak-uploads`).
- `EXPORT_DIR`: rendered output directory (default `/tmp/mind-of-ak-exports`).

## Deployment and safety notes

- The current implementation runs FFmpeg synchronously in the web process. Long renders may time out or consume too much memory/CPU on free hosting; this is a prototype, not production render infrastructure.
- Files in `/tmp` are ephemeral. A host restart or redeploy can remove sources and exports.
- There is no authentication or per-user project isolation yet. Do not upload confidential or sensitive footage to this public demo.
- Before production, add authentication, persistent object storage, background workers and a job queue, progress reporting, concurrency/rate limits, automatic cleanup, and monitoring.
- AI model keys must stay server-side. Any future voice/music/assets feature must respect provider terms and the relevant licences. Do not promise copyright safety without verifying asset rights.
- Video quality enhancement can improve perceived quality in suitable cases, but it cannot reliably recover details absent from the source. Keep enhancement optional and avoid synthetic-looking faces/textures.
