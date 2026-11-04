"""Dedicated FFmpeg render worker."""
import asyncio, logging, os, signal
from app import job_store
from app.main import _render_export_now, _render_timeline_now
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"))
log=logging.getLogger("mind-of-ak-worker")
POLL_SECONDS=max(1,int(os.getenv("WORKER_POLL_SECONDS","2")))
stopping=False
def _stop(*_):
    global stopping
    stopping=True
async def process_job(job):
    job_id=job["job_id"]
    try:
        payload = dict(job["payload"])
        segments = payload.pop("timeline_segments", None)
        if segments is not None:
            payload.pop("start_seconds", None)
            payload.pop("end_seconds", None)
            result = await _render_timeline_now(segments=segments, **payload)
        else:
            result = await _render_export_now(**payload)
        job_store.update_job(job_id,status="completed",progress=100,message="Render completed.",result=result)
        log.info("Completed render job %s",job_id)
    except Exception as exc:
        detail=getattr(exc,"detail",str(exc))
        job_store.update_job(job_id,status="failed",progress=0,message="Render failed.",error=str(detail)[:2000])
        log.exception("Render job %s failed",job_id)
async def main():
    job_store.init_db()
    job_store.recover_interrupted_jobs()
    while not stopping:
        job=job_store.claim_next()
        if job is None: await asyncio.sleep(POLL_SECONDS)
        else: await process_job(job)
if __name__=="__main__":
    signal.signal(signal.SIGTERM,_stop); signal.signal(signal.SIGINT,_stop)
    asyncio.run(main())
