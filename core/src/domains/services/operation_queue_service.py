# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Durable operation queue backed by the ``operations`` Postgres table.

Every state transition (enqueue, claim, complete, fail, cancel, reap) is
an atomic SQL statement guarded on the current status, so a late writer
can never resurrect a finished operation. The claim uses
``FOR UPDATE SKIP LOCKED`` so concurrent workers never block each other.
Operations are never retried: a failed or lost operation ends FAILED.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, cast, final
from uuid import UUID, uuid4

from sqlalchemy import CursorResult, func, select, text, update
from sqlalchemy.exc import IntegrityError

from src.domains.exceptions import SessionConflict
from src.domains.services.database_service import DatabaseService
from src.infrastructure.database import db
from src.infrastructure.database.models import Operation, Session
from src.shared.config.system_config import SchedulerConfig
from src.shared.constants import OperationStatus, OperationType
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging

_ACTIVE = (OperationStatus.PENDING, OperationStatus.RUNNING)


@final
class OperationQueueService:
    """Manages the lifecycle of durable operation rows."""

    def __init__(self, config: SchedulerConfig) -> None:
        self._config = config

    async def enqueue(
        self,
        session_id: UUID,
        kind: OperationType,
        params: dict[str, Any],
        schedule_id: int | None = None,
    ) -> Operation:
        """Queue an operation; 409 when the session already has an active one."""
        session_row = await db.get_by(Session, uuid=session_id)
        if session_row is None:
            raise ExceptionHandler(
                message=f"Session {session_id} not found.", error_code=404
            )
        try:
            op = await db.create(
                Operation,
                uuid=uuid4(),
                session_id=session_row.id,
                schedule_id=schedule_id,
                kind=kind,
                params=params,
                status=OperationStatus.PENDING,
                scheduled_at=datetime.now(timezone.utc),
                timeout_seconds=self._config.default_timeout_seconds,
            )
        except IntegrityError:
            raise SessionConflict(
                message=f"Session {session_id} already has an operation in flight.",
                error_code=409,
            )
        logging.info(
            f"Enqueued operation {op.uuid} ({kind.name}) for session {session_id}"
        )
        return op

    async def claim(self, worker_id: str) -> Operation | None:
        # Raw SQL: subquery + FOR UPDATE SKIP LOCKED + RETURNING is not
        # expressible through the ORM.
        sql = text("""
            UPDATE operations
            SET status           = :running,
                claimed_by       = :worker_id,
                started_at       = now(),
                lease_expires_at = now() + :lease,
                updated_at       = now()
            WHERE id = (
                SELECT id FROM operations
                WHERE status = :pending
                  AND scheduled_at <= now()
                ORDER BY scheduled_at, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id
        """)
        async with db.transaction() as session:
            result = await session.execute(
                sql,
                {
                    "running": OperationStatus.RUNNING.name,
                    "pending": OperationStatus.PENDING.name,
                    "worker_id": worker_id,
                    "lease": timedelta(seconds=self._config.lease_seconds),
                },
            )
            op_id = result.scalar_one_or_none()
        if op_id is None:
            return None
        op = await db.get_by(Operation, id=op_id)
        if op is not None:
            logging.info(f"Claimed operation {op.uuid} ({op.kind.name})")
        return op

    async def heartbeat(self, operation_id: int, worker_id: str) -> bool:
        """Extend the lease; False when the worker must stop (cancel or lost lease)."""
        async with db.transaction() as session:
            stmt = (
                update(Operation)
                .where(
                    Operation.id == operation_id,
                    Operation.claimed_by == worker_id,
                    Operation.status == OperationStatus.RUNNING,
                    Operation.cancel_requested.is_(False),
                )
                .values(
                    lease_expires_at=datetime.now(timezone.utc)
                    + timedelta(seconds=self._config.lease_seconds)
                )
            )
            res = await session.execute(stmt)
        return cast(CursorResult[Any], res).rowcount == 1

    async def complete(self, operation_id: int) -> None:
        await self.__finish(operation_id, OperationStatus.SUCCEEDED, None)
        logging.info(f"Operation {operation_id} succeeded")

    async def fail(self, operation_id: int, error: str) -> None:
        await self.__finish(operation_id, OperationStatus.FAILED, error)
        logging.info(f"Operation {operation_id} failed: {error}")

    async def mark_cancelled(self, operation_id: int) -> None:
        await self.__finish(
            operation_id, OperationStatus.CANCELLED, "Cancelled by user"
        )
        logging.info(f"Operation {operation_id} cancelled")

    async def __finish(
        self, operation_id: int, status: OperationStatus, error: str | None
    ) -> None:
        async with db.transaction() as session:
            stmt = (
                update(Operation)
                .where(Operation.id == operation_id, Operation.status.in_(_ACTIVE))
                .values(
                    status=status,
                    finished_at=datetime.now(timezone.utc),
                    lease_expires_at=None,
                    claimed_by=None,
                    error=error,
                )
            )
            _ = await session.execute(stmt)

    async def cancel(self, operation: Operation) -> None:
        """Cancel a pending op outright; flag a running one for its worker."""
        if operation.status is OperationStatus.PENDING:
            values: dict[str, Any] = {
                "status": OperationStatus.CANCELLED,
                "finished_at": datetime.now(timezone.utc),
                "error": "Cancelled by user",
            }
        elif operation.status is OperationStatus.RUNNING:
            values = {"cancel_requested": True}
        else:
            raise ExceptionHandler(
                message=f"Operation {operation.uuid} is already {operation.status.value}.",
                error_code=409,
            )
        async with db.transaction() as session:
            stmt = (
                update(Operation)
                .where(
                    Operation.id == operation.id, Operation.status == operation.status
                )
                .values(**values)
            )
            res = await session.execute(stmt)
            if cast(CursorResult[Any], res).rowcount == 0:
                raise ExceptionHandler(
                    message="Operation status changed concurrently.", error_code=409
                )
        logging.info(f"Cancel requested for operation {operation.uuid}")

    async def reap_expired_leases(self) -> int:
        """Fail RUNNING ops whose worker stopped heartbeating; free their sessions."""
        async with db.transaction() as session:
            stmt = (
                update(Operation)
                .where(
                    Operation.status == OperationStatus.RUNNING,
                    Operation.lease_expires_at < func.now(),
                )
                .values(
                    status=OperationStatus.FAILED,
                    finished_at=func.now(),
                    lease_expires_at=None,
                    claimed_by=None,
                    error="Worker lost (lease expired)",
                )
                .returning(Operation.session_id)
            )
            session_pks = list((await session.execute(stmt)).scalars().all())

        for pk in session_pks:
            session_row = await db.get_by(Session, id=pk)
            if session_row is None:
                continue
            try:
                await DatabaseService.mark_failed(
                    session_row.uuid, "The worker running this session was lost."
                )
                await DatabaseService.release_in_flight(session_row.uuid)
            except Exception:
                logging.exception(
                    f"Failed to clean up session {session_row.uuid} after reap"
                )
        return len(session_pks)

    async def get_operation(self, operation_id: UUID) -> Operation | None:
        return await db.get_by(Operation, uuid=operation_id)

    async def list_operations(
        self,
        *,
        user_pk: int,
        session_id: UUID | None = None,
        schedule_pk: int | None = None,
        kind: OperationType | None = None,
        status: OperationStatus | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Operation], int]:
        """Operations on sessions owned by ``user_pk``, newest first."""
        conditions = [Session.user_id == user_pk]
        if session_id is not None:
            conditions.append(Session.uuid == session_id)
        if schedule_pk is not None:
            conditions.append(Operation.schedule_id == schedule_pk)
        if kind is not None:
            conditions.append(Operation.kind == kind)
        if status is not None:
            conditions.append(Operation.status == status)

        async with db.session() as session:
            total = (
                await session.execute(
                    select(func.count(Operation.id))
                    .join(Operation.session)
                    .where(*conditions)
                )
            ).scalar_one()
            items = (
                (
                    await session.execute(
                        select(Operation)
                        .join(Operation.session)
                        .where(*conditions)
                        .order_by(Operation.created_at.desc(), Operation.id.desc())
                        .offset(offset)
                        .limit(limit)
                    )
                )
                .scalars()
                .unique()
                .all()
            )
        return list(items), total
