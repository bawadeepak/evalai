"""Durable job worker process.

Runs as a separate process (``evalai worker``). Claims jobs from the database,
heartbeats their leases, recovers expired leases left by dead workers, and
records its own heartbeat for the health endpoint. Several job slots run
concurrently on one asyncio loop; per-target concurrency limits are enforced by
the queue.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import socket
import time
import traceback
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import func, select

from eval_triage.api.app import build_context
from eval_triage.api.context import AppContext
from eval_triage.config import Settings, get_settings
from eval_triage.db.models import Job
from eval_triage.domain.enums import JobKind, JobStatus
from eval_triage.execution import jobs
from eval_triage.execution.common import Defer

log = logging.getLogger("eval_triage.worker")

Handler = Callable[[AppContext, Job, str], Awaitable[dict]]
HANDLERS: dict[str, Handler] = {}


def register_handler(kind: str, handler: Handler) -> None:
    HANDLERS[kind] = handler


def _default_handlers() -> None:
    from eval_triage.execution.grading import run_grade_job
    from eval_triage.execution.trial_runner import run_trial_job

    HANDLERS.setdefault(JobKind.TRIAL, run_trial_job)
    HANDLERS.setdefault(JobKind.GRADE, run_grade_job)
    try:
        from eval_triage.execution.background import register_background_handlers

        register_background_handlers(register_handler)
    except ImportError:  # pragma: no cover - optional during early milestones
        pass


class Worker:
    def __init__(self, settings: Settings | None = None, ctx: AppContext | None = None,
                 worker_id: str | None = None, slots: int | None = None) -> None:
        self.settings = settings or get_settings()
        self.ctx = ctx or build_context(self.settings)
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.slots = slots or self.settings.worker_slots
        self.stopping = False
        self.active: set[asyncio.Task] = set()
        _default_handlers()

    def stop(self) -> None:
        self.stopping = True

    def _after_job(self, job: Job) -> None:
        from eval_triage.execution.finalize import maybe_finalize, maybe_finalize_grading

        with self.ctx.db.write() as session:
            grading_run_id = (job.payload or {}).get("grading_run_id")
            if grading_run_id:
                maybe_finalize_grading(session, grading_run_id)
            if job.run_id:
                maybe_finalize(session, job.run_id)

    def _reconcile(self) -> None:
        from eval_triage.execution.finalize import reconcile_failed_jobs

        with self.ctx.db.write() as session:
            reconcile_failed_jobs(session)

    def _open_jobs(self) -> int:
        with self.ctx.db.read() as session:
            return session.scalar(select(func.count()).select_from(Job).where(
                Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING])))

    async def _handle(self, job: Job) -> None:
        settings = self.settings

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(settings.heartbeat_seconds)
                owned = await asyncio.to_thread(jobs.heartbeat, self.ctx.db, job.id, self.worker_id,
                                                settings.lease_seconds)
                if not owned:
                    log.warning("lost lease on job %s", job.id)
                    return

        beat = asyncio.create_task(heartbeat())
        try:
            handler = HANDLERS.get(job.kind)
            if handler is None:
                await asyncio.to_thread(jobs.fail, self.ctx.db, job.id, self.worker_id,
                                        {"code": "no_handler", "message": f"no handler for {job.kind}"})
                return
            result = await handler(self.ctx, job, self.worker_id)
            await asyncio.to_thread(jobs.complete, self.ctx.db, job.id, self.worker_id, result)
            # A job counts as open until it is completed, so completion is re-checked afterwards.
            await asyncio.to_thread(self._after_job, job)
        except Defer as deferral:
            await asyncio.to_thread(jobs.defer, self.ctx.db, job.id, self.worker_id, deferral.seconds, deferral.note)
        except Exception as exc:  # noqa: BLE001 - job failures are recorded, never crash the worker
            log.exception("job %s failed", job.id)
            await asyncio.to_thread(jobs.fail, self.ctx.db, job.id, self.worker_id,
                                    {"code": "job_exception", "message": f"{type(exc).__name__}: {exc}"[:1000],
                                     "traceback": traceback.format_exc(limit=8)}, 2.0)
        finally:
            beat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await beat

    async def run(self, once: bool = False, max_seconds: float | None = None) -> int:
        loop = asyncio.get_running_loop()
        with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
            loop.add_signal_handler(signal.SIGTERM, self.stop)
            loop.add_signal_handler(signal.SIGINT, self.stop)
        await asyncio.to_thread(jobs.register_worker, self.ctx.db, self.worker_id,
                                {"slots": self.slots, "pid": os.getpid()})
        started = time.monotonic()
        last_beat = last_recover = 0.0
        try:
            while not self.stopping:
                now = time.monotonic()
                if now - last_beat >= self.settings.heartbeat_seconds:
                    await asyncio.to_thread(jobs.register_worker, self.ctx.db, self.worker_id)
                    last_beat = now
                if now - last_recover >= max(self.settings.lease_seconds / 4, 0.2):
                    await asyncio.to_thread(jobs.recover_expired, self.ctx.db)
                    await asyncio.to_thread(self._reconcile)
                    last_recover = now
                self.active = {t for t in self.active if not t.done()}
                claimed = False
                while len(self.active) < self.slots and not self.stopping:
                    job = await asyncio.to_thread(jobs.claim_next, self.ctx.db, self.worker_id,
                                                  self.settings.lease_seconds)
                    if job is None:
                        break
                    claimed = True
                    self.active.add(asyncio.create_task(self._handle(job)))
                if once and not claimed and not self.active and await asyncio.to_thread(self._open_jobs) == 0:
                    break
                if max_seconds is not None and time.monotonic() - started > max_seconds:
                    break
                await asyncio.sleep(self.settings.worker_poll_seconds)
        finally:
            if self.active:
                await asyncio.gather(*self.active, return_exceptions=True)
            import sys as _sys

            bridges = _sys.modules.get("eval_triage.adapters.memoryai.bridge_client")
            if bridges is not None:
                await bridges.close_all()
            await asyncio.to_thread(jobs.unregister_worker, self.ctx.db, self.worker_id)
        return 0


def run_worker(once: bool = False, worker_id: str | None = None, settings: Settings | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return asyncio.run(Worker(settings=settings, worker_id=worker_id).run(once=once))


def drain(ctx: AppContext, max_seconds: float = 60.0, slots: int = 4) -> None:
    """Run jobs in-process until the queue is empty (tests and the demo seeder)."""
    asyncio.run(Worker(settings=ctx.settings, ctx=ctx, slots=slots).run(once=True, max_seconds=max_seconds))
