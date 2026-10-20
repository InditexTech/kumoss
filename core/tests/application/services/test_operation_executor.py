# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""OperationExecutor outcomes, with every collaborator mocked."""

import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from src.application.services.operation_executor import OperationExecutor
from src.domains.exceptions import SessionTerminal
from src.shared.config.system_config import SchedulerConfig
from src.shared.constants import OperationStatus, OperationType, SessionStatus
from src.shared.exceptions import ExceptionHandler

_MOD = "src.application.services.operation_executor"


async def _hang():
    await asyncio.sleep(10)


def _operation(kind=OperationType.DRIFT, params=None, timeout=60):
    return SimpleNamespace(
        id=7,
        uuid=uuid4(),
        session=SimpleNamespace(uuid=uuid4()),
        kind=kind,
        params=params if params is not None else {"q": "drift", "is_partial": True},
        timeout_seconds=timeout,
    )


class _ExecutorBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.queue = AsyncMock()
        self.queue.heartbeat.return_value = True
        self.ctx = MagicMock()
        self.ctx.id = uuid4()

        self.db = MagicMock()
        self.db.get_session_context = AsyncMock(return_value=self.ctx)
        self.db.assert_resumable = AsyncMock()
        self.db.is_session_blocked = AsyncMock(return_value=False)
        self.db.get_last_status = AsyncMock(
            return_value=SimpleNamespace(status=SessionStatus.FILTERING)
        )
        self.db.mark_completed = AsyncMock()
        self.db.mark_failed = AsyncMock()

        self.run_handler = AsyncMock()
        self.factory = MagicMock()
        for getter in (
            "get_terraform_crud_handler",
            "get_terraform_drift_handler",
            "get_terraform_import_handler",
            "get_terraform_apply_handler",
        ):
            getattr(self.factory, getter).return_value.handle = AsyncMock(
                return_value=self.run_handler
            )
        self.notify = AsyncMock()

        workspace = MagicMock()
        workspace.setup_call_dir = AsyncMock(return_value=Path("/tmp/call"))
        workspace.iac_root.return_value = Path("/tmp/call/infra")

        self._patches = [
            patch(f"{_MOD}.DatabaseService", self.db),
            patch(f"{_MOD}.ApplicationFactory", return_value=self.factory),
            patch(f"{_MOD}.WorkspaceService", return_value=workspace),
            patch(f"{_MOD}.PhoenixTracer"),
            patch(f"{_MOD}.tracer"),
            patch(
                f"{_MOD}.NotificationServiceClient.notify_exception_failure",
                self.notify,
            ),
        ]
        for p in self._patches:
            _ = p.start()
        self.executor = OperationExecutor(
            self.queue, SchedulerConfig(heartbeat_interval=0.01)
        )

    async def asyncTearDown(self):
        for p in self._patches:
            p.stop()


class TestSuccess(_ExecutorBase):
    async def test_runs_the_handler_and_completes(self):
        op = _operation()
        await self.executor.execute(op, "w1")

        self.factory.get_terraform_drift_handler.return_value.handle.assert_awaited_once_with(
            "drift", True
        )
        self.run_handler.assert_awaited_once()
        self.db.mark_completed.assert_awaited_once()
        self.queue.complete.assert_awaited_once_with(op.id)
        self.queue.fail.assert_not_awaited()

    async def test_dispatches_on_kind(self):
        cases = {
            OperationType.GENERATE: ("get_terraform_crud_handler", ("gen",)),
            OperationType.IMPORT: ("get_terraform_import_handler", ("gen", False)),
            OperationType.APPLY: ("get_terraform_apply_handler", ()),
        }
        for kind, (getter, args) in cases.items():
            with self.subTest(kind=kind):
                await self.executor.execute(_operation(kind, {"q": "gen"}), "w1")
                handle = getattr(self.factory, getter).return_value.handle
                handle.assert_awaited_with(*args)

    async def test_uncompleted_sessions_are_not_marked_completed(self):
        self.db.get_last_status.return_value = SimpleNamespace(
            status=SessionStatus.UNCOMPLETED
        )
        await self.executor.execute(_operation(), "w1")
        self.db.mark_completed.assert_not_awaited()
        self.queue.complete.assert_awaited_once()


class TestFailures(_ExecutorBase):
    async def test_finished_session_fails_without_running(self):
        self.db.assert_resumable.side_effect = SessionTerminal("finished", 409)
        op = _operation()
        await self.executor.execute(op, "w1")
        self.queue.fail.assert_awaited_once_with(op.id, "finished")
        self.queue.fail_unstarted_session.assert_awaited_once_with(
            op.session.uuid, "finished"
        )
        self.run_handler.assert_not_awaited()

    async def test_blocked_session_fails_only_the_queued_apply(self):
        self.db.is_session_blocked = AsyncMock(return_value=True)
        op = _operation(OperationType.APPLY, {})
        await self.executor.execute(op, "w1")
        self.queue.fail.assert_awaited_once()
        self.db.assert_resumable.assert_not_awaited()
        self.db.mark_failed.assert_not_awaited()
        self.run_handler.assert_not_awaited()

    async def test_handler_error_fails_the_operation_and_the_session(self):
        self.run_handler.side_effect = ExceptionHandler("kaput", 500)
        op = _operation()
        await self.executor.execute(op, "w1")
        self.queue.fail.assert_awaited_once_with(op.id, "runner failed: kaput")
        self.db.mark_failed.assert_awaited_once_with(
            self.ctx.id, "runner failed: kaput"
        )
        self.notify.assert_awaited_once()
        self.queue.complete.assert_not_awaited()

    async def test_unexpected_errors_do_not_leave_the_operation_running(self):
        self.run_handler.side_effect = RuntimeError("bug")
        op = _operation()
        await self.executor.execute(op, "w1")
        self.queue.fail.assert_awaited_once_with(
            op.id, "runner failed: unexpected error: bug"
        )

    async def test_timeout_fails_the_operation(self):
        self.run_handler.side_effect = _hang
        op = _operation(timeout=0.05)
        await self.executor.execute(op, "w1")
        self.queue.fail.assert_awaited_once_with(
            op.id, "runner failed: timed out after 0.05s"
        )


class TestCancellation(_ExecutorBase):
    async def test_user_cancel_stops_the_running_handler(self):
        self.run_handler.side_effect = _hang
        self.queue.heartbeat.return_value = False
        self.queue.get_operation.return_value = SimpleNamespace(
            status=OperationStatus.RUNNING, cancel_requested=True
        )
        op = _operation()

        await asyncio.wait_for(self.executor.execute(op, "w1"), timeout=2)

        self.queue.mark_cancelled.assert_awaited_once_with(op.id)
        self.queue.complete.assert_not_awaited()
        self.queue.fail.assert_not_awaited()
        self.db.mark_failed.assert_awaited_once()

    async def test_worker_shutdown_fails_the_operation_and_propagates(self):
        started = asyncio.Event()

        async def hang():
            started.set()
            await asyncio.sleep(10)

        self.run_handler.side_effect = hang
        op = _operation()
        task = asyncio.create_task(self.executor.execute(op, "w1"))
        _ = await started.wait()
        _ = task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.queue.fail.assert_awaited_once_with(
            op.id,
            "runner failed: Interrupted by a worker shutdown",
        )
        self.queue.mark_cancelled.assert_not_awaited()

    async def test_lost_lease_leaves_the_session_to_the_reaper(self):
        self.run_handler.side_effect = _hang
        self.queue.heartbeat.return_value = False
        self.queue.get_operation.return_value = SimpleNamespace(
            status=OperationStatus.FAILED, cancel_requested=False
        )
        self.queue.fail.return_value = False  # already reaped
        op = _operation()

        await asyncio.wait_for(self.executor.execute(op, "w1"), timeout=2)

        self.db.mark_failed.assert_not_awaited()
        self.queue.mark_cancelled.assert_not_awaited()
        self.queue.fail.assert_awaited_once_with(op.id, "Worker lost (lease expired)")

    async def test_unrenewable_lease_stops_the_pipeline(self):
        self.run_handler.side_effect = _hang
        self.queue.heartbeat.side_effect = ConnectionError("db down")
        self.queue.fail.return_value = True  # nobody reaped it
        self.executor = OperationExecutor(
            self.queue, SchedulerConfig(heartbeat_interval=0.01, lease_seconds=0.05)
        )
        op = _operation()

        await asyncio.wait_for(self.executor.execute(op, "w1"), timeout=2)

        self.queue.fail.assert_awaited_once_with(op.id, "Worker lost (lease expired)")
        self.db.mark_failed.assert_awaited_once_with(
            self.ctx.id, "The worker running this session was lost."
        )
