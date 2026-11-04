# Mind of AK AI Studio

Mind of AK AI Studio is a browser-based creator workspace being developed in stages. This repository contains video upload/validation, FFmpeg scene-change analysis, a durable single-host render queue, basic MP4 export, and optional SRT subtitle burn-in. It is **not yet a complete AI editor**.

## Current features

- Responsive dark-glass and gold interface.
- Upload video files in MP4, MOV, M4V, WEBM, or MKV format.
- Server-side file size limit via `MAX_UPLOAD_MB` (default 2048 MB / 2 GB; deployment memory, request limits, disk and proxy settings can impose lower limits).
- Validate that an upload contains a readable video stream using FFprobe.
- Read duration, resolution, codec, frame rate, and audio-stream presence.
- Find visual scene-change candidates using FFmpeg's scene-change filter. This is visual-change detection, not semantic AI scene understanding.
- Export an MP4 with original, vertical 9:16, or square framing.
- Choose high, balanced, or smaller-file export quality.
- Trim a clip by start/end seconds; this starter limits each export to 5 minutes.
- Download the rendered MP4 to the user's device.
- Save an edit brief in the current browser using local storage (not sent to an AI provider).
- Evidence-based validation API for video stream metadata, SRT syntax/timing, subtitle overlap and duration bounds, and optional supplied-script/transcript text comparison.

## Not implemented yet

- AI prompt-to-edit and automatic scene-by-scene directing.
- Automatic highlight selection, beat matching, transitions, and gaming montage.
- Automatic captions/transcription, including Tamil-English code-switching. Speech recognition is not integrated; audio/script matching remains `NOT_VERIFIED` unless a transcript is supplied by a separate trusted ASR step.
- Tamil/English TTS, original music, sleep ambience, and kids' story narration.
- AI asset search and licensing verification, generated diagrams, puzzle drawings, or B-roll insertion.
- Natural denoise, stabilization, color grading, super-resolution/upscaling, or any guarantee of increased source detail.
- Voice Studio, Style DNA, project accounts, cloud project persistence, or collaborative editing.

The roadmap takes inspiration from professional editing workflows (timeline control, precise trimming, audio mixing, color management, captions, proxy workflows, and export presets) without copying proprietary source code, brand assets, or protected UI designs from other products.

## Durable render queue and subtitle export

- Render requests are persisted in SQLite rather than an in-memory dictionary.
- The API enqueues work; a separate worker process executes FFmpeg.
- Worker restarts re-queue interrupted jobs. Old completed/failed job records are pruned after `JOB_RETENTION_DAYS` (default 7).
- Queue state is shared across API and worker processes and survives API restarts.
- This starter queue is for one EC2 host and one worker, not a multi-instance distributed queue.
- Progress currently reports queue/worker state, not exact FFmpeg frame percentage.
- Optional SRT subtitles can be pasted into export settings and burned into the MP4. Timestamps must be relative to the selected export clip; subtitle size is limited to 1 MB and 2,000 cues. Subtitle appearance supports four font sizes, top/middle/bottom placement, and white/yellow text.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`.

For the full queue/worker setup, use `docker compose up --build` and open `http://127.0.0.1:8000`. FFmpeg, FFprobe and Noto fonts are installed in the Docker image. A local Python-only run needs FFmpeg and FFprobe installed separately.

## API

- `GET /` — web interface.
- `GET /api/health` — service and media-tool status.
- `POST /api/upload` — multipart field `file`; validates the uploaded video.
- `GET /api/analyze/{stored_name}` — technical metadata and visual scene-change candidates.
- `POST /api/validate` — multipart fields `stored_name`, optional `script`, optional `.srt` file field `srt_file`, and optional externally generated `transcript_text`. Returns PASS/WARNING/FAIL/NOT_VERIFIED checks. A supplied transcript is compared as text only; it is not generated from audio here.
- `POST /api/export` — queues an export. Supports `stored_name`, `preset`, `framing`, `resolution`, `quality`, trim times, color/fade/audio controls, optional `subtitle_srt`, `subtitle_size`, `subtitle_position`, and `subtitle_color`.
- `GET /api/export-status/{job_id}` — render queue/worker status.
- `GET /api/download/{filename}` — download a completed export.

## Environment variables

- `MAX_UPLOAD_MB`: upload limit (default 2048 MB). Set this to a value your hosting platform can safely accept.
- `UPLOAD_DIR`: source upload directory (default `/tmp/mind-of-ak-uploads`).
- `EXPORT_DIR`: rendered output directory (default `/tmp/mind-of-ak-exports`).
- `JOB_DB_PATH`: SQLite render queue database path (set to `/data/jobs.sqlite3` in Compose).
- `JOB_RETENTION_DAYS`: retain completed/failed queue records for this many days (default 7).
- `MAX_RENDER_EDGE`: maximum output long edge in pixels (default 640; increase only on a host with enough memory).

## Cloudflare deployment

See [deploy/cloudflare/README.md](deploy/cloudflare/README.md). The Cloudflare starter uses a Worker for routing/static assets and a Cloudflare Container for the existing FastAPI + FFmpeg application. Containers require the Workers Paid plan; this is not a zero-cost deployment. Durable R2 media storage and authentication remain required before public production.


## Deployment and safety notes

- FFmpeg renders run in a separate worker, but the queue is SQLite-backed and designed for one host/one worker only. It is not a distributed production queue. Long renders may still consume substantial CPU, memory and disk. The 2 GB upload default is only an application-level limit and does not guarantee that the host or reverse proxy accepts files that large.
- Files in `/tmp` are ephemeral. A host restart or redeploy can remove sources and exports.
- There is no authentication or per-user project isolation yet. Do not upload confidential or sensitive footage to this public demo.
- Before public production, add authentication, per-user project isolation, private object storage, distributed job orchestration, accurate FFmpeg progress, stronger quotas/rate limits, and monitoring.
- AI model keys must stay server-side. Any future voice/music/assets feature must respect provider terms and the relevant licences. Do not promise copyright safety without verifying asset rights.
- Video quality enhancement can improve perceived quality in suitable cases, but it cannot reliably recover details absent from the source. Keep enhancement optional and avoid synthetic-looking faces/textures.


## Validation guarantees and limits

Validation is deliberately conservative: `NOT_VERIFIED` is not a pass. SRT checks cover parseability, timestamp ordering, cue duration, overlap warnings, and whether cues exceed the source duration. Optional script comparison only compares the script against a transcript supplied by another process; it does not transcribe the audio or guarantee pronunciation/semantic correctness. This build does not yet provide automatic speech recognition, image-to-narration semantic matching, a frame-accurate visual timeline, or post-render audio/subtitle/image auditing. Those checks must remain unverified until implemented and tested. Absolute perfect validation cannot be guaranteed by automated checks alone; uncertain cases require human review.
