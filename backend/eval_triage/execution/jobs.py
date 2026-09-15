"""Durable job queue in SQLite.

Claims happen inside ``BEGIN IMMEDIATE`` transactions, so two workers can never
claim the same job. Leases expire (default 60 s) unless heartbeated (default
every 10 s); expired jobs are recovered by any worker. Per-key concurrency
limits (for example one MemoryAI episode at a time) are enforced at claim time.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from eval_triage.db.engine import Database
from eval_triage.db.models import Job, WorkerHeartbeat
from eval_triage.db.types import utcnow
from eval_triage.domain.enums import JobStatus


def enqueue(session, kind: str, payload: dict[str, Any], *, run_id: str | None = None,
            concurrency_key: str = "default", concurrency_limit: int = 4, priority: int = 0,
            max_attempts: int = 3, delay_seconds: float = 0.0) -> Job:
    job = Job(kind=kind, payload=payload, run_id=run_id, concurrency_key=concurrency_key,
              concurrency_limit=concurrency_limit, priority=priority, max_attempts=max_attempts,
              next_available_at=utcnow() + timedelta(seconds=delay_seconds))
    session.add(job)
    session.flush()
    return job


def claim_next(db: Database, worker_id: str, lease_seconds: float, kinds: list[str] | None = None,
               now: datetime | None = None) -> Job | None:
    with db.write() as session:
        now = now or utcnow()
        running = dict(session.execute(
            select(Job.concurrency_key, func.count()).where(Job.status == JobStatus.RUNNING)
            .group_by(Job.concurrency_key)).all())
        query = select(Job).where(Job.status == JobStatus.QUEUED, Job.next_available_at <= now)
        if kinds:
            query = query.where(Job.kind.in_(kinds))
        for job in session.scalars(query.order_by(Job.priority, Job.created_at, Job.id).limit(500)):
            if running.get(job.concurrency_key, 0) >= job.concurrency_limit:
                continue
            job.status = JobStatus.RUNNING
            job.lease_owner = worker_id
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            job.heartbeat_at = now
            job.attempts += 1
            session.flush()
            return job
    return None


def heartbeat(db: Database, job_id: str, worker_id: str, lease_seconds: float) -> bool:
    """Extend the lease. Returns False if this worker no longer owns the job."""
    with db.write() as session:
        job = session.get(Job, job_id)
        if job is None or job.status != JobStatus.RUNNING or job.lease_owner != worker_id:
            return False
        now = utcnow()
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        return True


def complete(db: Database, job_id: str, worker_id: str, result: dict[str, Any] | None = None) -> bool:
    with db.write() as session:
        job = session.get(Job, job_id)
        if job is None or job.lease_owner != worker_id or job.status != JobStatus.RUNNING:
            return False
        job.status = JobStatus.SUCCEEDED
        job.result = result or {}
        job.finished_at = utcnow()
        job.lease_expires_at = None
        return True


def fail(db: Database, job_id: str, worker_id: str, error: dict[str, Any], retry_delay: float | None = None) -> str:
    with db.write() as session:
        job = session.get(Job, job_id)
        if job is None or job.lease_owner != worker_id:
            return "lost"
        job.error = error
        job.lease_owner = None
        job.lease_expires_at = None
        if retry_delay is not None and job.attempts < job.max_attempts:
            job.status = JobStatus.QUEUED
            job.next_available_at = utcnow() + timedelta(seconds=retry_delay)
            return "requeued"
        job.status = JobStatus.FAILED
        job.finished_at = utcnow()
        return "failed"


def defer(db: Database, job_id: str, worker_id: str, delay_seconds: float, note: str) -> None:
    """Put a job back without counting it as a failed attempt (e.g. waiting for a paired trial)."""
    with db.write() as session:
        job = session.get(Job, job_id)
        if job is None or job.lease_owner != worker_id:
            return
        job.status = JobStatus.QUEUED
        job.attempts = max(0, job.attempts - 1)
        job.lease_owner = None
        job.lease_expires_at = None
        job.next_available_at = utcnow() + timedelta(seconds=delay_seconds)
        job.result = {"deferred": note}


def cancel_queued(session, run_id: str, kinds: list[str] | None = None) -> int:
    query = select(Job).where(Job.run_id == run_id, Job.status == JobStatus.QUEUED)
    if kinds:
        query = query.where(Job.kind.in_(kinds))
    count = 0
    for job in session.scalars(query):
        job.status = JobStatus.CANCELLED
        job.finished_at = utcnow()
        count += 1
    return count


def recover_expired(db: Database, now: datetime | None = None) -> list[str]:
    """Requeue running jobs whose lease expired (their worker died or stalled)."""
    with db.write() as session:
        now = now or utcnow()
        expired = session.scalars(select(Job).where(Job.status == JobStatus.RUNNING,
                                                   Job.lease_expires_at < now)).all()
        ids = []
        for job in expired:
            ids.append(job.id)
            job.error = {"code": "lease_expired", "message": f"worker {job.lease_owner} stopped heartbeating",
                         "previous_owner": job.lease_owner}
            job.lease_owner = None
            job.lease_expires_at = None
            if job.attempts < job.max_attempts:
                job.status = JobStatus.QUEUED
                job.next_available_at = now
            else:
                job.status = JobStatus.FAILED
                job.finished_at = now
        return ids


def register_worker(db: Database, worker_id: str, info: dict[str, Any] | None = None) -> None:
    with db.write() as session:
        row = session.get(WorkerHeartbeat, worker_id)
        now = utcnow()
        if row is None:
            session.add(WorkerHeartbeat(worker_id=worker_id, pid=os.getpid(), started_at=now, heartbeat_at=now,
                                        info=info or {}))
        else:
            row.heartbeat_at = now
            row.pid = os.getpid()
            if info is not None:
                row.info = info


def unregister_worker(db: Database, worker_id: str) -> None:
    with db.write() as session:
        row = session.get(WorkerHeartbeat, worker_id)
        if row is not None:
            session.delete(row)
