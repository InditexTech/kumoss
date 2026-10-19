# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Durable operation queue backed by the ``operations`` Postgres table.

Every state transition (enqueue, claim, complete, fail, cancel, reap) is
an atomic SQL statement guarded on the current status, so a late writer
can never resurrect a finished operation. The claim uses
``FOR UPDATE SKIP LOCKED`` so concurrent workers never block each other.
Operations are never retried: a failed or lost operation ends FAILED.
Every timestamp is the database's ``now()``, never the app clock, so lease
math stays consistent across hosts whose clocks drift.
"""

from datetime import timedelta
from typing import Any, cast, final
from uuid import UUID, uuid4

from sqlalchemy import CursorResult, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.domains.exceptions import SessionConflict
from src.domains.services.database_service import DatabaseService
from src.infrastructure.database import db
from src.infrastructure.database.models import Operation, Session
from src.shared.config.system_config import SchedulerConfig
from src.shared.constants import OperationStatus, OperationType, SessionStatus
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging

_ACTIVE = (OperationStatus.PENDING, OperationStatus.RUNNING)
# Kinds whose running terraform job can't be stopped from the core.
_UNINTERRUPTIBLE = frozenset({OperationType.APPLY, OperationType.IMPORT})


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
                scheduled_at=func.now(),
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

    async def claim(
        self, worker_id: str, allow_scheduled: bool = True
    ) -> Operation | None:
        """Claim the next due operation, interactive calls before cron fires.

        ``allow_scheduled=False`` claims interactive operations only, so a
        worker can keep slots free for users while cron runs are queued.
        """
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
                  AND (:allow_scheduled OR schedule_id IS NULL)
                ORDER BY (schedule_id IS NOT NULL), scheduled_at, id
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
                    "allow_scheduled": allow_scheduled,
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
                    lease_expires_at=func.now()
                    + timedelta(seconds=self._config.lease_seconds)
                )
            )
            res = await session.execute(stmt)
        return cast(CursorResult[Any], res).rowcount == 1

    async def complete(
        self, operation_id: int, *, release_session: bool = False
    ) -> bool:
        finished = await self.__finish(
            operation_id, OperationStatus.SUCCEEDED, None, release_session
        )
        logging.info(f"Operation {operation_id} succeeded")
        return finished

    async def fail(
        self, operation_id: int, error: str, *, release_session: bool = False
    ) -> bool:
        finished = await self.__finish(
            operation_id, OperationStatus.FAILED, error, release_session
        )
        logging.info(f"Operation {operation_id} failed: {error}")
        return finished

    async def mark_cancelled(
        self, operation_id: int, *, release_session: bool = False
    ) -> bool:
        finished = await self.__finish(
            operation_id,
            OperationStatus.CANCELLED,
            "Cancelled by user",
            release_session,
        )
        logging.info(f"Operation {operation_id} cancelled")
        return finished

    async def __finish(
        self,
        operation_id: int,
        status: OperationStatus,
        error: str | None,
        release_session: bool,
    ) -> bool:
        """End an active operation; True when this call made the transition.

        ``release_session`` frees the session's ``in_flight`` lock in the
        same transaction, so no call can find the active-operation slot free
        while the lock is still held, and a crash can't leave the lock set.
        An operation that already ended (e.g. reaped) frees nothing, so a
        late worker can never release a successor's lock.
        """
        async with db.transaction() as session:
            stmt = (
                update(Operation)
                .where(Operation.id == operation_id, Operation.status.in_(_ACTIVE))
                .values(
                    status=status,
                    finished_at=func.now(),
                    lease_expires_at=None,
                    claimed_by=None,
                    error=error,
                )
                .returning(Operation.session_id)
            )
            session_pk = (await session.execute(stmt)).scalar_one_or_none()
            if release_session and session_pk is not None:
                await self.__release_sessions(session, [session_pk])
        return session_pk is not None

    @staticmethod
    async def __release_sessions(session: AsyncSession, session_pks: list[int]) -> None:
        _ = await session.execute(
            update(Session)
            .where(Session.id.in_(session_pks))
            .values(in_flight=False, updated_at=func.now())
        )

    async def cancel(self, operation: Operation) -> None:
        """Cancel a pending op outright; flag a running one for its worker."""
        if operation.status is OperationStatus.PENDING:
            values: dict[str, Any] = {
                "status": OperationStatus.CANCELLED,
                "finished_at": func.now(),
                "error": "Cancelled by user",
            }
        elif (
            operation.status is OperationStatus.RUNNING
            and operation.kind in _UNINTERRUPTIBLE
        ):
            # Cancelling stops only the core pipeline, not the terraform job
            # it already submitted to the IaC service, which would keep
            # changing state/infrastructure after we report it stopped.
            raise ExceptionHandler(
                message=f"A running {operation.kind.value} cannot be cancelled.",
                error_code=409,
            )
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
        if operation.status is OperationStatus.PENDING:
            await self.fail_unstarted_session(
                operation.session.uuid, "Operation cancelled before it started"
            )
        logging.info(f"Cancel requested for operation {operation.uuid}")

    async def fail_unstarted_session(self, session_id: UUID, msg: str) -> None:
        """End a session whose first operation never ran.

        Its latest status is still the STARTED written at creation, which
        clients render as in progress forever. A session that already ran
        a round keeps its status: it stays usable for the next call.
        """
        try:
            last = await DatabaseService.get_last_status(session_id)
            if last.status is SessionStatus.STARTED:
                await DatabaseService.mark_failed(session_id, msg)
        except Exception:
            logging.exception(f"Failed to end unstarted session {session_id}")

    async def has_active_for_schedule(self, schedule_pk: int) -> bool:
        """True while an operation fired by the schedule is pending or running."""
        async with db.session() as session:
            found = (
                await session.execute(
                    select(Operation.id)
                    .where(
                        Operation.schedule_id == schedule_pk,
                        Operation.status.in_(_ACTIVE),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
        return found is not None

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
            # Freed with the reap itself: a crash before the status writes
            # below must not leave these sessions locked forever.
            if session_pks:
                await self.__release_sessions(session, session_pks)

        for pk in session_pks:
            session_row = await db.get_by(Session, id=pk)
            if session_row is None:
                continue
            try:
                await DatabaseService.mark_failed(
                    session_row.uuid, "The worker running this session was lost."
                )
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
