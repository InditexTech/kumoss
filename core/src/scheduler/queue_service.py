# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Durable operation queue backed by the ``operations`` Postgres table.

Every state transition (enqueue, claim, complete, fail, cancel, reap)
is an atomic SQL statement. The claim uses ``FOR UPDATE SKIP LOCKED``
so concurrent workers never block each other.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text, update

from src.infrastructure.database import db
from src.infrastructure.database.models import Session
from src.scheduler.config import SchedulerConfig
from src.scheduler.constants import OperationKind, OperationStatus
from src.scheduler.models import Operation
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging
from src.domains.services.database_service import DatabaseService


class OperationQueueService:
    """Manages the lifecycle of durable operation rows."""

    def __init__(self, config: SchedulerConfig) -> None:
        self._config = config

    async def enqueue(
        self,
        session_uuid: _uuid.UUID,
        kind: OperationKind,
        params: dict[str, Any],
        dedup_key: str,
        schedule_id: int,
    ) -> Operation:
        session_row = await db.get_by(Session, uuid=session_uuid)
        if session_row is None:
            raise ExceptionHandler(
                message=f"Session {session_uuid} not found.", error_code=404
            )

        now = datetime.now(timezone.utc)
        op = await db.create(
            Operation,
            uuid=_uuid.uuid4(),
            session_id=session_row.id,
            kind=kind,
            params=params,
            status=OperationStatus.PENDING,
            scheduled_at=now,
            attempt=0,
            max_attempts=self._config.default_max_attempts,
            timeout_seconds=self._config.default_timeout_seconds,
            dedup_key=dedup_key,
            schedule_id=schedule_id,
        )
        logging.info(
            f"Enqueued operation {op.uuid} ({kind.value}) for session {session_uuid}"
        )
        return op

    async def claim(self, worker_id: str) -> Operation | None:
        lease = timedelta(seconds=self._config.lease_seconds)

        sql = text("""
            UPDATE operations
            SET status      = :running,
                claimed_by  = :worker_id,
                attempt     = attempt + 1,
                started_at  = now(),
                lease_expires_at = now() + :lease_interval
            WHERE id = (
                SELECT id FROM operations
                WHERE status = :pending
                  AND scheduled_at <= now()
                ORDER BY scheduled_at, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING *
        """)

        async with db.transaction() as session:
            result = await session.execute(
                sql,
                {
                    "running": OperationStatus.RUNNING.value,
                    "pending": OperationStatus.PENDING.value,
                    "worker_id": worker_id,
                    "lease_interval": lease,
                },
            )
            row = result.mappings().first()

        if row is None:
            return None

        op = await db.get_by(Operation, id=row["id"])
        logging.info(f"Claimed operation {op.uuid} (attempt {op.attempt})")
        return op

    async def heartbeat(self, operation_id: int, worker_id: str) -> bool:
        lease = timedelta(seconds=self._config.lease_seconds)

        async with db.transaction() as session:
            stmt = (
                update(Operation)
                .where(
                    Operation.id == operation_id,
                    Operation.claimed_by == worker_id,
                    Operation.status == OperationStatus.RUNNING,
                )
                .values(lease_expires_at=datetime.now(timezone.utc) + lease)
            )
            await session.execute(stmt)

        op = await db.get_by(Operation, id=operation_id)
        if op is None:
            return False
        return not op.cancel_requested

    async def complete(self, operation_id: int) -> None:
        now = datetime.now(timezone.utc)
        async with db.transaction() as session:
            stmt = (
                update(Operation)
                .where(Operation.id == operation_id)
                .values(
                    status=OperationStatus.SUCCEEDED,
                    finished_at=now,
                    lease_expires_at=None,
                    claimed_by=None,
                )
            )
            await session.execute(stmt)
        logging.info(f"Operation {operation_id} completed")

    async def fail(
        self, operation_id: int, error: str, *, retryable: bool = False
    ) -> None:
        op = await db.get_by(Operation, id=operation_id)
        if op is None:
            return

        now = datetime.now(timezone.utc)

        if retryable and op.attempt < op.max_attempts:
            backoff = min(
                self._config.retry_backoff_seconds * (2 ** (op.attempt - 1)),
                self._config.retry_backoff_cap,
            )
            async with db.transaction() as session:
                stmt = (
                    update(Operation)
                    .where(Operation.id == operation_id)
                    .values(
                        status=OperationStatus.PENDING,
                        scheduled_at=now + timedelta(seconds=backoff),
                        lease_expires_at=None,
                        claimed_by=None,
                        error=error,
                    )
                )
                await session.execute(stmt)
            logging.info(
                f"Operation {operation_id} retryable failure "
                f"(attempt {op.attempt}/{op.max_attempts}), "
                f"backoff {backoff:.0f}s"
            )
        else:
            async with db.transaction() as session:
                stmt = (
                    update(Operation)
                    .where(Operation.id == operation_id)
                    .values(
                        status=OperationStatus.FAILED,
                        finished_at=now,
                        lease_expires_at=None,
                        claimed_by=None,
                        error=error,
                    )
                )
                await session.execute(stmt)
            logging.info(f"Operation {operation_id} failed: {error}")

    async def cancel(self, operation_uuid: _uuid.UUID) -> None:
        op = await db.get_by(Operation, uuid=operation_uuid)
        if op is None:
            raise ExceptionHandler(
                message=f"Operation {operation_uuid} not found.", error_code=404
            )

        if op.status == OperationStatus.PENDING:
            async with db.transaction() as session:
                stmt = (
                    update(Operation)
                    .where(
                        Operation.id == op.id,
                        Operation.status == OperationStatus.PENDING,
                    )
                    .values(
                        status=OperationStatus.CANCELLED,
                        finished_at=datetime.now(timezone.utc),
                    )
                )
                result = await session.execute(stmt)
                if result.rowcount == 0:  # type: ignore[union-attr]
                    raise ExceptionHandler(
                        message="Operation status changed concurrently.",
                        error_code=409,
                    )
            logging.info(f"Cancelled pending operation {operation_uuid}")

        elif op.status == OperationStatus.RUNNING:
            async with db.transaction() as session:
                stmt = (
                    update(Operation)
                    .where(
                        Operation.id == op.id,
                        Operation.status == OperationStatus.RUNNING,
                    )
                    .values(cancel_requested=True)
                )
                result = await session.execute(stmt)
                if result.rowcount == 0:  # type: ignore[union-attr]
                    raise ExceptionHandler(
                        message="Operation status changed concurrently.",
                        error_code=409,
                    )
            logging.info(
                f"Cancel requested for running operation {operation_uuid}"
            )

        else:
            raise ExceptionHandler(
                message=f"Operation {operation_uuid} is already terminal ({op.status.value}).",
                error_code=409,
            )

    async def reap_expired_leases(self) -> int:

        now = datetime.now(timezone.utc)

        async with db.session() as session:
            stmt = (
                select(Operation)
                .where(
                    Operation.status == OperationStatus.RUNNING,
                    Operation.lease_expires_at < now,
                )
            )
            result = await session.execute(stmt)
            expired_ops = list(result.scalars().all())

        reaped = 0
        for op in expired_ops:
            try:
                session_row = await db.get_by(Session, id=op.session_id)
                if session_row is not None:
                    try:
                        await DatabaseService.release_in_flight(session_row.uuid)
                    except Exception:
                        logging.warning(
                            f"Failed to release in_flight for session "
                            f"{session_row.uuid} during reap"
                        )

                if op.attempt >= op.max_attempts:
                    await self.fail(
                        op.id,
                        f"Lease expired after {op.attempt} attempt(s)",
                    )
                else:
                    backoff = min(
                        self._config.retry_backoff_seconds
                        * (2 ** (op.attempt - 1)),
                        self._config.retry_backoff_cap,
                    )
                    async with db.transaction() as sess:
                        stmt = (
                            update(Operation)
                            .where(Operation.id == op.id)
                            .values(
                                status=OperationStatus.PENDING,
                                scheduled_at=now + timedelta(seconds=backoff),
                                lease_expires_at=None,
                                claimed_by=None,
                                error="Lease expired, requeued",
                            )
                        )
                        await sess.execute(stmt)
                    logging.info(
                        f"Reaped operation {op.uuid}: requeued "
                        f"(attempt {op.attempt}/{op.max_attempts})"
                    )
                reaped += 1
            except Exception:
                logging.exception(f"Error reaping operation {op.uuid}")

        return reaped

    async def get_operation(self, operation_uuid: _uuid.UUID) -> Operation | None:
        return await db.get_by(Operation, uuid=operation_uuid)

    async def list_operations(
        self,
        *,
        session_id: int | None = None,
        kind: OperationKind | None = None,
        status: OperationStatus | None = None,
        schedule_id: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Operation], int]:
        filters: dict[str, Any] = {}
        if session_id is not None:
            filters["session_id"] = session_id
        if kind is not None:
            filters["kind"] = kind
        if status is not None:
            filters["status"] = status
        if schedule_id is not None:
            filters["schedule_id"] = schedule_id

        offset = (page - 1) * page_size
        return await db.query(
            Operation,
            order_by="created_at",
            order_desc=True,
            offset=offset,
            limit=page_size,
            **filters,
        )
