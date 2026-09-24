# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0


from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import update

from src.application.factory import ApplicationFactory
from src.domains.entities.session import SessionContext
from src.domains.exceptions import SessionConflict, SessionTerminal
from src.domains.services.database_service import DatabaseService
from src.domains.services.tracer_service import tracer
from src.infrastructure.database import db
from src.infrastructure.database.models import Session
from src.infrastructure.external.notification_service import NotificationServiceClient
from src.infrastructure.filesystem import WorkspaceService
from src.infrastructure.telemetry.phoenix.phoenix_tracer import PhoenixTracer
from src.scheduler.config import SchedulerConfig
from src.scheduler.constants import OperationKind, OperationStatus
from src.scheduler.models import Operation
from src.scheduler.queue_service import OperationQueueService
from src.shared.constants import SessionStatus
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging


class OperationExecutor:
    """Executes a single claimed operation through the full handler pipeline."""

    def __init__(
        self, queue: OperationQueueService, config: SchedulerConfig
    ) -> None:
        self._queue = queue
        self._config = config

    async def execute(self, operation: Operation, worker_id: str) -> None:
        session_row = await db.get_by(Session, id=operation.session_id)
        if session_row is None:
            await self._queue.fail(
                operation.id, "Session row not found", retryable=False
            )
            return

        session_uuid = session_row.uuid
        ctx = None
        call_dir = None
        tracer_token = None
        heartbeat_task = None

        try:
            ctx = await DatabaseService.get_session_context(session_uuid)
        except ExceptionHandler as e:
            await self._queue.fail(
                operation.id, f"Cannot load session context: {e.message}",
                retryable=False,
            )
            return

        try:
            await DatabaseService.acquire_in_flight(session_uuid)
        except SessionConflict:
            await self._reschedule(operation)
            return
        except SessionTerminal:
            await self._queue.fail(
                operation.id, "Session is terminal", retryable=False
            )
            return

        try:
            tracer_token = tracer.set_current_tracer(
                tracer=PhoenixTracer(
                    session_id=ctx.id,
                    user_id=ctx.user_id,
                    branch_name=ctx.branch_name,
                    cloud=ctx.terraform_prv,
                    repo_uri=ctx.repo_uri,
                    iac_path=ctx.iac_path,
                    operation=ctx.operation,
                )
            )

            heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(operation.id, worker_id)
            )

            workspace = WorkspaceService()
            call_dir = await workspace.setup_call_dir(
                session_id=ctx.id,
                repo_uri=ctx.repo_uri,
                branch=ctx.branch_name,
            )
            ctx.set_call_dir(call_dir / ctx.iac_path)

            async with asyncio.timeout(operation.timeout_seconds):
                run_handler = await self._build_handler(
                    operation.kind, operation.params, ctx
                )
                await run_handler()

            last = await DatabaseService.get_last_status(ctx.id)
            if last.status is not SessionStatus.UNCOMPLETED:
                await DatabaseService.mark_completed(ctx.id, ctx.operation.name)

            await self._queue.complete(operation.id)

        except ExceptionHandler as e:
            msg = f"runner failed: {e.message}"
            logging.error(f"{msg} (session {session_uuid})")
            await DatabaseService.mark_failed(session_uuid, msg)
            try:
                await NotificationServiceClient.notify_exception_failure(
                    session_uuid, ctx.user_id if ctx else "", msg
                )
            except Exception:
                logging.debug("Notification dispatch skipped")
            await self._queue.fail(operation.id, msg, retryable=False)

        except TimeoutError:
            msg = f"Operation timed out after {operation.timeout_seconds}s"
            logging.error(f"{msg} (session {session_uuid})")
            await self._queue.fail(operation.id, msg, retryable=True)

        except asyncio.CancelledError:
            logging.info(
                f"Operation {operation.uuid} cancelled (session {session_uuid})"
            )
            await self._queue.fail(
                operation.id, "Cancelled", retryable=False
            )
            raise

        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task
            if tracer_token is not None:
                tracer.reset_current_tracer(tracer_token)
            if call_dir is not None:
                WorkspaceService().cleanup(call_dir)
            try:
                await DatabaseService.release_in_flight(session_uuid)
            except Exception:
                logging.warning(
                    f"Failed to release in_flight for session {session_uuid}"
                )

    async def _build_handler(
        self,
        kind: OperationKind,
        params: dict[str, Any],
        ctx: SessionContext,
    ) -> Callable[[], Awaitable[Any]]:
        factory = ApplicationFactory(session_ctx=ctx)

        match kind:
            case OperationKind.DRIFT:
                handler = factory.get_terraform_drift_handler()
                return await handler.handle(
                    params["q"], params.get("is_partial", False)
                )

            case _:
                raise ExceptionHandler(
                    message=f"Operation kind '{kind.value}' is not yet enabled "
                    f"in the scheduler.",
                    error_code=501,
                )

    async def _heartbeat_loop(
        self, operation_id: int, worker_id: str
    ) -> None:
        while True:
            await asyncio.sleep(self._config.heartbeat_interval)
            try:
                alive = await self._queue.heartbeat(operation_id, worker_id)
                if not alive:
                    raise asyncio.CancelledError("cancel_requested by user")
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.warning(
                    f"Heartbeat failed for operation {operation_id}"
                )

    async def _reschedule(self, operation: Operation) -> None:

        backoff = min(
            self._config.retry_backoff_seconds,
            self._config.retry_backoff_cap,
        )
        now = datetime.now(timezone.utc)

        async with db.transaction() as session:
            stmt = (
                update(Operation)
                .where(Operation.id == operation.id)
                .values(
                    status=OperationStatus.PENDING,
                    scheduled_at=now + timedelta(seconds=backoff),
                    lease_expires_at=None,
                    claimed_by=None,
                    attempt=operation.attempt - 1,
                    error="Session busy, rescheduled",
                )
            )
            await session.execute(stmt)
        logging.info(
            f"Rescheduled operation {operation.uuid} "
            f"(session busy, attempt not consumed)"
        )
