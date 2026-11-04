import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from app import job_store
class JobStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.patch=patch.object(job_store,"DB_PATH",Path(self.tmp.name)/"jobs.sqlite3")
        self.patch.start(); job_store.init_db()
    def tearDown(self):
        self.patch.stop(); self.tmp.cleanup()
    def test_queue_lifecycle(self):
        jid=job_store.enqueue({"stored_name":"sample.mp4"})
        self.assertEqual(job_store.get_job(jid)["status"],"queued")
        claimed=job_store.claim_next(); self.assertEqual(claimed["job_id"],jid)
        job_store.update_job(jid,status="completed",progress=100,message="done",result={"url":"/download"})
        self.assertEqual(job_store.get_job(jid)["result"]["url"],"/download")
    def test_queue_limit(self):
        for _ in range(5): job_store.enqueue({})
        with self.assertRaises(RuntimeError): job_store.enqueue({})
    def test_claim_once(self):
        job_store.enqueue({})
        self.assertIsNotNone(job_store.claim_next())
        self.assertIsNone(job_store.claim_next())
if __name__=="__main__": unittest.main()
