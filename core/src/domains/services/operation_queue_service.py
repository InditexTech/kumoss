# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Durable operation queue backed by the ``operations`` Postgres table.

Persistence lives in ``DatabaseService`` (one status-guarded statement per
transition, ``FOR UPDATE SKIP LOCKED`` claims, database-clock leases); this
service applies the scheduler config and decides what each transition means
for the session. Operations are never retried: a failed or lost operation
ends FAILED.
"""

from typing import Any, ClassVar, final
from uuid import UUID

from src.domains.services.database_service import DatabaseService
from src.infrastructure.database.models import Operation
from src.shared.config.system_config import SchedulerConfig
from src.shared.constants import OperationStatus, OperationType, SessionStatus
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging


@final
class OperationQueueService:
    """Manages the lifecycle of durable operation rows."""

    # Written when a worker stops heartbeating (by the reaper, or by the
    # worker itself once it can't renew its lease).
    LOST_OPERATION_MSG: ClassVar[str] = "Worker lost (lease expired)"
    LOST_SESSION_MSG: ClassVar[str] = "The worker running this session was lost."

    # Kinds whose running terraform job can't be stopped from the core.
    _UNINTERRUPTIBLE: ClassVar[frozenset[OperationType]] = frozenset(
        {OperationType.APPLY, OperationType.IMPORT}
    )

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
        op = await DatabaseService.create_operation(
            session_id=session_id,
            kind=kind,
            params=params,
            timeout_seconds=self._config.default_timeout_seconds,
            schedule_id=schedule_id,
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
        op = await DatabaseService.claim_operation(
            worker_id, self._config.lease_seconds, allow_scheduled
        )
        if op is not None:
            logging.info(f"Claimed operation {op.uuid} ({op.kind.name})")
        return op

    async def heartbeat(self, operation_id: int, worker_id: str) -> bool:
        """Extend the lease; False when the worker must stop (cancel or lost lease)."""
        return await DatabaseService.renew_operation_lease(
            operation_id, worker_id, self._config.lease_seconds
        )

    async def complete(self, operation_id: int) -> bool:
        finished = await DatabaseService.finish_operation(
            operation_id, OperationStatus.SUCCEEDED, None
        )
        logging.info(f"Operation {operation_id} succeeded")
        return finished

    async def fail(self, operation_id: int, error: str) -> bool:
        finished = await DatabaseService.finish_operation(
            operation_id, OperationStatus.FAILED, error
        )
        logging.info(f"Operation {operation_id} failed: {error}")
        return finished

    async def mark_cancelled(self, operation_id: int) -> bool:
        finished = await DatabaseService.finish_operation(
            operation_id, OperationStatus.CANCELLED, "Cancelled by user"
        )
        logging.info(f"Operation {operation_id} cancelled")
        return finished

    async def cancel(self, operation: Operation) -> None:
        """Cancel a pending op outright; flag a running one for its worker."""
        if operation.status is OperationStatus.PENDING:
            changed = await DatabaseService.cancel_pending_operation(
                operation.id, "Cancelled by user"
            )
        elif (
            operation.status is OperationStatus.RUNNING
            and operation.kind in self._UNINTERRUPTIBLE
        ):
            # Cancelling stops only the core pipeline, not the terraform job
            # it already submitted to the IaC service, which would keep
            # changing state/infrastructure after we report it stopped.
            raise ExceptionHandler(
                message=f"A running {operation.kind.value} cannot be cancelled.",
                error_code=409,
            )
        elif operation.status is OperationStatus.RUNNING:
            changed = await DatabaseService.request_operation_cancel(operation.id)
        else:
            raise ExceptionHandler(
                message=f"Operation {operation.uuid} is already {operation.status.value}.",
                error_code=409,
            )
        if not changed:
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
        return await DatabaseService.has_active_schedule_operation(schedule_pk)

    async def reap_expired_leases(self) -> int:
        """Fail RUNNING ops whose worker stopped heartbeating; free their sessions."""
        session_ids = await DatabaseService.reap_expired_operations(
            self.LOST_OPERATION_MSG
        )
        for session_id in session_ids:
            try:
                await DatabaseService.mark_failed(session_id, self.LOST_SESSION_MSG)
            except Exception:
                logging.exception(f"Failed to clean up session {session_id} after reap")
        return len(session_ids)

    async def get_operation(self, operation_id: UUID) -> Operation | None:
        return await DatabaseService.get_operation(operation_id)

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
        return await DatabaseService.list_operations(
            user_pk=user_pk,
            session_id=session_id,
            schedule_pk=schedule_pk,
            kind=kind,
            status=status,
            offset=offset,
            limit=limit,
        )
