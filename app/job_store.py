"""SQLite-backed durable render queue for a single-host deployment."""
from __future__ import annotations
import json, os, sqlite3, time, uuid
from pathlib import Path
from typing import Any
DB_PATH = Path(os.getenv("JOB_DB_PATH", "/tmp/mind-of-ak-jobs.sqlite3"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
def _connect():
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=30000")
    return db
def init_db():
    with _connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS render_jobs (job_id TEXT PRIMARY KEY,status TEXT NOT NULL,progress INTEGER NOT NULL DEFAULT 0,message TEXT NOT NULL DEFAULT '',payload_json TEXT NOT NULL,result_json TEXT,error TEXT,created_at REAL NOT NULL,updated_at REAL NOT NULL,started_at REAL)""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_render_jobs_status_created ON render_jobs(status, created_at)")
def enqueue(payload: dict[str, Any], max_active: int = 5) -> str:
    now=time.time()
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        active=db.execute("SELECT COUNT(*) FROM render_jobs WHERE status IN ('queued','running')").fetchone()[0]
        if active >= max_active: raise RuntimeError("The render queue is full. Wait for an existing export to finish.")
        job_id=uuid.uuid4().hex
        db.execute("INSERT INTO render_jobs(job_id,status,progress,message,payload_json,created_at,updated_at) VALUES(?,'queued',0,?,?,?,?)",(job_id,"Waiting for a render worker.",json.dumps(payload),now,now))
        return job_id
def claim_next():
    now=time.time()
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE render_jobs SET status='failed',progress=0,error='Worker stopped or render exceeded its lease.',message='Render interrupted.',updated_at=? WHERE status='running' AND started_at < ?",(now,now-600))
        row=db.execute("SELECT job_id,payload_json FROM render_jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if row is None: return None
        changed=db.execute("UPDATE render_jobs SET status='running',progress=5,message='Worker started FFmpeg render.',started_at=?,updated_at=? WHERE job_id=? AND status='queued'",(now,now,row["job_id"])).rowcount
        return {"job_id":row["job_id"],"payload":json.loads(row["payload_json"])} if changed else None
def update_job(job_id: str, *, status: str, progress: int, message: str, result=None, error=None):
    if status not in {"queued","running","completed","failed"}: raise ValueError("Invalid render job status.")
    with _connect() as db:
        db.execute("UPDATE render_jobs SET status=?,progress=?,message=?,result_json=?,error=?,updated_at=? WHERE job_id=?",(status,max(0,min(100,int(progress))),message,json.dumps(result) if result is not None else None,error,time.time(),job_id))
def get_job(job_id: str):
    with _connect() as db: row=db.execute("SELECT * FROM render_jobs WHERE job_id=?",(job_id,)).fetchone()
    if row is None: return None
    item=dict(row); item["result"]=json.loads(item["result_json"]) if item["result_json"] else None
    item.pop("result_json",None); item.pop("payload_json",None); return item
