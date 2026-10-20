# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Runs one claimed operation through the full session pipeline."""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any, ClassVar, final

from src.application.factory import ApplicationFactory
from src.domains.entities import SessionContext
from src.domains.services.database_service import DatabaseService
from src.domains.services.operation_queue_service import OperationQueueService
from src.domains.services.tracer_service import tracer
from src.infrastructure.database.models import Operation
from src.infrastructure.external.notification_service import NotificationServiceClient
from src.infrastructure.filesystem import WorkspaceService
from src.infrastructure.telemetry.phoenix.phoenix_tracer import PhoenixTracer
from src.shared.config.system_config import SchedulerConfig
from src.shared.constants import OperationStatus, OperationType, SessionStatus
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging


@final
class OperationExecutor:
    """Acquire → tracer → clone → handler → complete, for any operation kind.

    The pipeline runs in its own task so the heartbeat can stop it when the
    user cancels or the lease is lost; the session's in-flight lock is
    released with the operation's final transition, whatever the outcome.
    """

    # Why the heartbeat stopped the pipeline.
    _CANCELLED: ClassVar[str] = "cancelled by user"
    _LEASE_LOST: ClassVar[str] = "lease lost"

    def __init__(self, queue: OperationQueueService, config: SchedulerConfig) -> None:
        self._queue = queue
        self._config = config
        self._workspace = WorkspaceService()

    async def execute(self, operation: Operation, worker_id: str) -> None:
        session_id = operation.session.uuid
        try:
            ctx = await DatabaseService.get_session_context(session_id)
            if (
                operation.kind is OperationType.APPLY
                and await DatabaseService.is_session_blocked(session_id)
            ):
                # Re-checked here: the session may have been blocked while the
                # apply waited in the queue. Only the operation fails, so the
                # session can be unblocked and the apply retried.
                raise ExceptionHandler(
                    message=f"Session {session_id} is blocked; apply is not allowed.",
                    error_code=409,
                )
            await DatabaseService.acquire_in_flight(session_id)
        except ExceptionHandler as e:
            # Never got the lock: the session is gone, finished, blocked or busy.
            _ = await self._queue.fail(operation.id, e.message)
            await self._queue.fail_unstarted_session(session_id, e.message)
            return

        run = asyncio.create_task(self._run(operation, ctx))
        heartbeat = asyncio.create_task(self._heartbeat_loop(operation, worker_id, run))
        # Every finisher also frees in_flight, in the same transaction.
        finish: Callable[[], Awaitable[bool]] = partial(
            self._queue.complete, operation.id, release_session=True
        )
        lease_lost = False
        try:
            await run
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                # Worker shutdown: don't leave the op RUNNING until the reaper.
                finish = await self.__fail(
                    operation, ctx, "Interrupted by a worker shutdown"
                )
                raise
            if await heartbeat == self._LEASE_LOST:
                # Usually the reaper already failed the op and the session and
                # freed the lock; the finisher is then a no-op.
                lease_lost = True
                finish = partial(
                    self._queue.fail,
                    operation.id,
                    OperationQueueService.LOST_OPERATION_MSG,
                    release_session=True,
                )
            else:
                await DatabaseService.mark_failed(ctx.id, "Operation cancelled by user")
                finish = partial(
                    self._queue.mark_cancelled, operation.id, release_session=True
                )
        except TimeoutError:
            finish = await self.__fail(
                operation, ctx, f"timed out after {operation.timeout_seconds}s"
            )
        except ExceptionHandler as e:
            finish = await self.__fail(operation, ctx, e.message)
        except Exception as e:
            logging.exception(f"Unexpected error in operation {operation.uuid}")
            finish = await self.__fail(operation, ctx, f"unexpected error: {e}")
        finally:
            _ = heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                _ = await heartbeat
            finished = await finish()
            if lease_lost and finished:
                # Not reaped (the database was unreachable for everyone):
                # report the session the way the reaper would have.
                try:
                    await DatabaseService.mark_failed(
                        ctx.id, OperationQueueService.LOST_SESSION_MSG
                    )
                except Exception:
                    logging.exception(f"Failed to report lost session {ctx.id}")

    async def _run(self, operation: Operation, ctx: SessionContext) -> None:
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
        call_dir = None
        try:
            async with asyncio.timeout(operation.timeout_seconds):
                call_dir = await self._workspace.setup_call_dir(
                    session_id=ctx.id,
                    repo_uri=ctx.repo_uri,
                    branch=ctx.branch_name,
                )
                ctx.set_call_dir(self._workspace.iac_root(call_dir, ctx.iac_path))
                run_handler = await self._build_handler(
                    operation.kind, operation.params, ctx
                )
                await run_handler()
            last = await DatabaseService.get_last_status(ctx.id)
            if last.status is not SessionStatus.UNCOMPLETED:
                await DatabaseService.mark_completed(ctx.id, ctx.operation.name)
        finally:
            tracer.reset_current_tracer(tracer_token)
            if call_dir is not None:
                self._workspace.cleanup(call_dir)

    @staticmethod
    async def _build_handler(
        kind: OperationType, params: dict[str, Any], ctx: SessionContext
    ) -> Callable[[], Awaitable[Any]]:
        factory = ApplicationFactory(session_ctx=ctx)
        match kind:
            case OperationType.GENERATE:
                return await factory.get_terraform_crud_handler().handle(params["q"])
            case OperationType.DRIFT:
                return await factory.get_terraform_drift_handler().handle(
                    params["q"], params.get("is_partial", False)
                )
            case OperationType.IMPORT:
                return await factory.get_terraform_import_handler().handle(
                    params["q"], params.get("is_partial", False)
                )
            case OperationType.APPLY:
                return await factory.get_terraform_apply_handler().handle()

    async def _heartbeat_loop(
        self, operation: Operation, worker_id: str, run: asyncio.Task[None]
    ) -> str | None:
        """Extend the lease until ``run`` ends; stop it when the heartbeat is
        refused, or can't be renewed before the lease runs out, and return
        why (``_CANCELLED`` or ``_LEASE_LOST``)."""
        loop = asyncio.get_running_loop()
        renewed_at = loop.time()
        while not run.done():
            await asyncio.sleep(self._config.heartbeat_interval)
            try:
                if await self._queue.heartbeat(operation.id, worker_id):
                    renewed_at = loop.time()
                    continue
                reason = await self.__stop_reason(operation)
            except Exception:
                logging.warning(f"Heartbeat failed for operation {operation.id}")
                if loop.time() - renewed_at < self._config.lease_seconds:
                    continue
                # The lease may have expired and been reaped by another
                # replica: stop rather than keep working on a session we
                # may no longer own.
                reason = self._LEASE_LOST
            logging.info(f"Stopping operation {operation.id}: {reason}")
            _ = run.cancel()
            return reason
        return None

    async def __stop_reason(self, operation: Operation) -> str:
        current = await self._queue.get_operation(operation.uuid)
        if (
            current is not None
            and current.status is OperationStatus.RUNNING
            and current.cancel_requested
        ):
            return self._CANCELLED
        return self._LEASE_LOST

    async def __fail(
        self, operation: Operation, ctx: SessionContext, reason: str
    ) -> Callable[[], Awaitable[bool]]:
        """Report the failure on the session; return the op-row finisher."""
        msg = f"runner failed: {reason}"
        logging.error(f"{msg} (session {ctx.id})")
        try:
            await DatabaseService.mark_failed(ctx.id, msg)
            await NotificationServiceClient.notify_exception_failure(
                ctx.id, ctx.user_id, msg
            )
        except Exception:
            logging.exception(f"Failed to report failure of session {ctx.id}")
        return partial(self._queue.fail, operation.id, msg, release_session=True)
