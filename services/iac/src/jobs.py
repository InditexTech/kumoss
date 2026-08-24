# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""In-memory job registry for asynchronous terraform operations.

Submissions create an ``asyncio.Task`` that waits on the workspace's
FIFO queue, runs the operation, and records the outcome on the
``JobRecord``. Two failure planes are kept distinct:

* Terraform-level failures are returned by the operation as a result
  with a non-zero ``exit_code`` — the job still ends ``succeeded``.
* Service-level faults (unexpected exceptions, cancellation on
  shutdown) end the job ``failed`` with a ``Problem`` whose ``status``
  is the HTTP code an equivalent synchronous API would have returned.

Records live in process memory only (consistent with the rest of the
service's single-process state) and expire ``ttl_seconds`` after
reaching a terminal state; expired or lost jobs poll as 404.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path

from .models import (
    Job,
    JobKind,
    JobStatus,
    OperationResult,
    Problem,
)

logger = logging.getLogger(__name__)

JobResult = OperationResult
Pipeline = Callable[[], Awaitable[JobResult]]


class WorkspaceQueue:
    """Per-workspace FIFO: one job at a time per resolved path.

    Backed by one ``asyncio.Lock`` per path — lock waiters wake in FIFO
    order, so jobs run in task-creation (= submission) order. Locks are
    dropped once no job holds or awaits them, so the dict does not grow
    with workspace churn.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._holders: dict[str, int] = {}

    @asynccontextmanager
    async def acquire(self, path: Path) -> AsyncIterator[None]:
        key = str(path.resolve())
        lock = self._locks.setdefault(key, asyncio.Lock())
        self._holders[key] = self._holders.get(key, 0) + 1
        if lock.locked():
            logger.info(
                "workspace busy, queueing workspace=%s waiters=%d",
                key,
                self._holders[key] - 1,
            )
        try:
            async with lock:
                yield
        finally:
            self._holders[key] -= 1
            if not self._holders[key]:
                del self._holders[key]
                del self._locks[key]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class JobRecord:
    job_id: str
    kind: JobKind
    workspace: Path
    created_at: datetime = field(default_factory=_utcnow)
    status: JobStatus = "queued"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: JobResult | None = None
    error: Problem | None = None
    # asyncio holds only weak task references; this keeps the job alive.
    task: asyncio.Task | None = None
    expires_at: float | None = None  # time.monotonic(), set on terminal

    def to_model(self) -> Job:
        return Job(
            job_id=uuid.UUID(self.job_id),
            kind=self.kind,
            status=self.status,
            created_at=self.created_at,
            started_at=self.started_at,
            finished_at=self.finished_at,
            result=self.result,
            error=self.error,
        )


class JobRegistry:
    def __init__(self, ttl_seconds: int, workspace_queue: WorkspaceQueue) -> None:
        self._ttl = ttl_seconds
        self._queue = workspace_queue
        self._jobs: dict[str, JobRecord] = {}

    def submit(self, kind: JobKind, workspace: Path, pipeline: Pipeline) -> JobRecord:
        self._sweep()
        record = JobRecord(job_id=str(uuid.uuid4()), kind=kind, workspace=workspace)
        record.task = asyncio.create_task(
            self._run(record, pipeline), name=f"iac-job-{record.job_id}"
        )
        self._jobs[record.job_id] = record
        logger.info("job submitted job_id=%s kind=%s", record.job_id, kind)
        return record

    def get(self, job_id: str) -> JobRecord | None:
        self._sweep()
        return self._jobs.get(job_id)

    async def shutdown(self) -> None:
        pending = [
            r.task
            for r in self._jobs.values()
            if r.task is not None and not r.task.done()
        ]
        for task in pending:
            task.cancel()
        if pending:
            logger.warning("cancelling %d unfinished job(s) on shutdown", len(pending))
            await asyncio.gather(*pending, return_exceptions=True)

    async def _run(self, record: JobRecord, pipeline: Pipeline) -> None:
        try:
            async with self._queue.acquire(record.workspace):
                record.status = "running"
                record.started_at = _utcnow()
                result = await pipeline()
            self._succeed(record, result)
        except asyncio.CancelledError:
            self._fail(record, 503, "Service shut down before the job finished.")
            raise
        except Exception as exc:
            logger.exception("job crashed job_id=%s", record.job_id)
            self._fail(record, 500, str(exc))

    # The terminal transitions below are synchronous on purpose: pollers
    # must never observe a terminal status with its companion fields
    # (finished_at, result/error, expires_at) still unset.

    def _succeed(self, record: JobRecord, result: JobResult) -> None:
        record.finished_at = _utcnow()
        record.expires_at = time.monotonic() + self._ttl
        record.result = result
        record.status = "succeeded"
        logger.info("job succeeded job_id=%s", record.job_id)

    def _fail(self, record: JobRecord, status_code: int, detail: str) -> None:
        record.finished_at = _utcnow()
        record.expires_at = time.monotonic() + self._ttl
        record.error = Problem(
            title=HTTPStatus(status_code).phrase, status=status_code, detail=detail
        )
        record.status = "failed"
        logger.warning(
            "job failed job_id=%s status=%d detail=%s",
            record.job_id,
            status_code,
            detail[:500],
        )

    def _sweep(self) -> None:
        now = time.monotonic()
        expired = [
            job_id
            for job_id, r in self._jobs.items()
            if r.expires_at is not None and r.expires_at <= now
        ]
        for job_id in expired:
            del self._jobs[job_id]
        if expired:
            logger.info("swept %d expired job record(s)", len(expired))
