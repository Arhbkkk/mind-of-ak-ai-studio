# Mind of AK AI Studio

A starter MVP for a browser-based video editing studio.

## Included
- Responsive dark-glass and gold interface
- FastAPI health endpoint
- Video upload endpoint with extension and size checks
- Dockerfile with FFmpeg installed
- Render Blueprint for deployment

## Run locally
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Open http://localhost:8000.

## MVP limits
This starter does not yet perform AI editing, generate subtitles, synthesize speech, implement Voice Studio or Style DNA, or export edited videos. Uploaded files are stored temporarily on the server and may disappear when hosting restarts. Add authentication, persistent storage, rate limits, and background render jobs before production use.

## Environment variables
- `MAX_UPLOAD_MB`: upload size limit (default 250)
- `UPLOAD_DIR`: upload directory (default `/tmp/mind-of-ak-uploads`)
