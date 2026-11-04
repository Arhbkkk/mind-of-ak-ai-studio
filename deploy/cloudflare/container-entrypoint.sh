#!/bin/sh
set -eu
python -m app.worker &
WORKER_PID=$!
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" &
API_PID=$!
cleanup() {
  kill "$WORKER_PID" "$API_PID" 2>/dev/null || true
  wait "$WORKER_PID" "$API_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT
wait "$API_PID"
