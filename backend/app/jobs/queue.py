"""Job queue stored in the main database.

Went with this over Celery + Redis: a handful of report jobs a day doesn't
justify another service, and keeping jobs next to the data means the job and
the report row commit together. Postgres' FOR UPDATE SKIP LOCKED handles
multiple workers. If volume ever grows, only this module changes.
"""
from __future__ import annotations

import socket
import os
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db import is_postgres
from ..models import Job, utcnow

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
STALE_AFTER = timedelta(minutes=15)


def enqueue(db: Session, kind: str, payload: dict[str, Any], max_attempts: int = 3) -> Job:
    job = Job(kind=kind, payload=payload, max_attempts=max_attempts)
    db.add(job)
    db.flush()
    return job


def claim_next(db: Session, worker_id: str = WORKER_ID) -> Job | None:
    """Atomically claim the oldest queued job, or return None."""
    _requeue_stale(db)
    if is_postgres():
        job = db.scalar(
            select(Job)
            .where(Job.status == "queued")
            .order_by(Job.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            db.commit()
            return None
        job.status, job.locked_by = "running", worker_id
        job.attempts += 1
        job.started_at = utcnow()
        db.commit()
        return job

    # SQLite: optimistic claim with a conditional UPDATE (single writer DB).
    for _ in range(5):
        candidate = db.scalar(select(Job.id).where(Job.status == "queued").order_by(Job.id).limit(1))
        if candidate is None:
            return None
        res = db.execute(
            update(Job)
            .where(Job.id == candidate, Job.status == "queued")
            .values(status="running", locked_by=worker_id, attempts=Job.attempts + 1, started_at=utcnow())
        )
        db.commit()
        if res.rowcount == 1:
            return db.get(Job, candidate)
    return None


def complete(db: Session, job: Job, result: dict[str, Any] | None = None) -> None:
    job.status = "done"
    job.result = result or {}
    job.finished_at = utcnow()
    job.error = None
    db.commit()


def fail(db: Session, job: Job, error: str) -> None:
    """Retry until max_attempts, then mark failed."""
    job.error = error[-4000:]
    if job.attempts < job.max_attempts:
        job.status = "queued"
        job.locked_by = None
    else:
        job.status = "failed"
        job.finished_at = utcnow()
    db.commit()


def _requeue_stale(db: Session) -> None:
    """Jobs stuck in 'running' (worker crashed) go back to the queue."""
    cutoff = utcnow() - STALE_AFTER
    db.execute(
        update(Job)
        .where(Job.status == "running", Job.started_at < cutoff)
        .values(status="queued", locked_by=None)
    )
    db.commit()
