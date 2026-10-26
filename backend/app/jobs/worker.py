"""Job worker. Run standalone (``python -m app.jobs.worker``) or embedded in the API."""
from __future__ import annotations

import logging
import threading
import time
import traceback

from ..db import SessionLocal
from ..models import ReportRun, utcnow
from . import queue

log = logging.getLogger("ledgerline.worker")


def handle(db, job) -> dict:
    if job.kind == "report.generate":
        from ..reporting.pipeline import GateError, generate

        run = db.get(ReportRun, job.payload["report_run_id"])
        run.status = "running"
        db.commit()
        try:
            generate(db, run)
        except GateError as exc:
            # Not retryable: a human has to resolve breaks first. The job itself is done.
            db.rollback()
            run = db.get(ReportRun, job.payload["report_run_id"])
            run.status, run.error, run.finished_at = "blocked", str(exc), utcnow()
            db.commit()
            return {"report_run_id": run.id, "blocked": str(exc)}
        return {"report_run_id": run.id, "fingerprint": run.fingerprint}
    raise ValueError(f"Unknown job kind {job.kind}")


def process_one() -> bool:
    """Claim and run one job. Returns False if the queue was empty."""
    with SessionLocal() as db:
        job = queue.claim_next(db)
        if job is None:
            return False
        try:
            result = handle(db, job)
            queue.complete(db, job, result)
        except Exception as exc:  # noqa: BLE001 - record any failure on the job
            db.rollback()
            job = db.merge(job)
            log.error("Job %s failed: %s", job.id, exc)
            queue.fail(db, job, f"{exc}\n{traceback.format_exc(limit=5)}")
            if job.status == "failed" and job.kind == "report.generate":
                run = db.get(ReportRun, job.payload["report_run_id"])
                if run and run.status != "failed":
                    run.status, run.error, run.finished_at = "failed", str(exc), utcnow()
                    db.commit()
        return True


def run_forever(poll_seconds: float = 1.0, stop: threading.Event | None = None) -> None:
    log.info("Worker %s started", queue.WORKER_ID)
    while stop is None or not stop.is_set():
        try:
            busy = process_one()
        except Exception:  # noqa: BLE001 - keep the worker alive
            log.exception("Worker loop error")
            busy = False
        if not busy:
            time.sleep(poll_seconds)


def start_embedded() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=run_forever, kwargs={"poll_seconds": 0.5, "stop": stop},
                     name="ledgerline-worker", daemon=True).start()
    return stop


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run_forever()
