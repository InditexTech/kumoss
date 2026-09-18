# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Round-lifecycle tests for the generate and drift handlers.

All collaborators are mocked. The generate handler tests assert when the
round's workspace is promoted into the session's pinned slot (only after a
successful round) and that the drift pre-check runs on the validated
targets with session changes filtered out. They also cover the session
lock the generate round writes: compliance violations and high-impact
reports both block it, each with its own notification. The drift handler
tests assert that drift resolution runs unfiltered on the resolved
targets.
"""

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.application.exceptions import SetLockError, TerraformValidationFailedError
from src.application.use_cases.terraform_crud_handler import TerraformCRUDHandler
from src.application.use_cases.terraform_drift_handler import TerraformDriftHandler
from src.domains.dto import TerraformValidationDTO
from src.domains.services.database_service import DatabaseService
from src.shared.config import system_config


def _dto(validation: bool, targets: list[str] | None = None) -> TerraformValidationDTO:
    return TerraformValidationDTO(
        validation=validation,
        feedback="" if validation else "boom",
        terraform_plan="plan output",
        terraform_targets=targets or [],
    )


def _report(level: str) -> MagicMock:
    report = MagicMock()
    report.potential_impact.banner.level = level
    report.potential_impact.banner.description = f"{level} impact detail"
    return report


class _HandlerTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        lock_patcher = patch.object(
            DatabaseService, "set_lock", AsyncMock(return_value=True)
        )
        self.set_lock = lock_patcher.start()
        self.addCleanup(lock_patcher.stop)

        self.session_svc = AsyncMock()
        self.terraform_svc = AsyncMock()
        self.validation_svc = AsyncMock()
        self.template_svc = AsyncMock()
        self.filter_svc = AsyncMock()
        self.filter_svc.filter.return_value = (True, "")
        self.report_svc = AsyncMock()
        self.target_svc = AsyncMock()
        self.drift_svc = AsyncMock()
        self.compliance_svc = AsyncMock()
        self.compliance_svc.check.return_value = MagicMock(passed=True)
        self.workspace_svc = MagicMock()
        self.ctx = MagicMock()
        self.ctx.call_dir = Path("/workspaces/sid/call-id")
        # The drift round json.dumps() the serialized history into the
        # report content, so this one has to be real data.
        self.ctx.history.serialize.return_value = [
            {"user": "check drift", "assistant": "done"}
        ]


class _CrudHandlerTestCase(_HandlerTestCase):
    def _handler(self) -> TerraformCRUDHandler:
        return TerraformCRUDHandler(
            session_ctx=self.ctx,
            session_service=self.session_svc,
            terraform_service=self.terraform_svc,
            validation_service=self.validation_svc,
            template_service=self.template_svc,
            requests_filter_service=self.filter_svc,
            report_service=self.report_svc,
            target_service=self.target_svc,
            drift_service=self.drift_svc,
            compliance_service=self.compliance_svc,
            workspace_service=self.workspace_svc,
        )


class TestCrudHandlerPinning(_CrudHandlerTestCase):
    async def test_successful_round_pins_the_workspace(self):
        self.validation_svc.generate_and_validate.return_value = _dto(True)

        task = await self._handler().handle("create a bucket")
        await task()

        self.workspace_svc.pin_workspace.assert_called_once_with(
            self.ctx.id, self.ctx.call_dir
        )
        self.session_svc.save.assert_awaited_once()

    async def test_successful_round_runs_filtered_drift_precheck_on_targets(self):
        self.validation_svc.generate_and_validate.return_value = _dto(
            True, targets=["module.kvt_001", "azurerm_storage_account.sta_001"]
        )
        self.template_svc.compose_template.return_value = "conventions"

        task = await self._handler().handle("create a bucket")
        await task()

        self.drift_svc.detect_and_resolve_drift.assert_awaited_once_with(
            filter_session_changes=True,
            targets=["module.kvt_001", "azurerm_storage_account.sta_001"],
            conventions="conventions",
            max_iterations=2,
        )

    async def test_failed_validation_does_not_pin_nor_check_drift(self):
        self.validation_svc.generate_and_validate.return_value = _dto(False)
        self.report_svc.summarize_problem.return_value = "it broke"

        task = await self._handler().handle("create a bucket")
        with self.assertRaises(TerraformValidationFailedError):
            await task()

        self.workspace_svc.pin_workspace.assert_not_called()
        self.drift_svc.detect_and_resolve_drift.assert_not_awaited()

    async def test_rejected_request_does_not_pin(self):
        self.filter_svc.filter.return_value = (False, "out of scope")

        task = await self._handler().handle("make me a sandwich")
        await task()

        self.workspace_svc.pin_workspace.assert_not_called()
        self.validation_svc.generate_and_validate.assert_not_awaited()


class TestCrudHandlerBlocking(_CrudHandlerTestCase):
    def setUp(self):
        super().setUp()
        flag_patcher = patch.object(
            system_config.orchestration, "block_on_high_impact", True
        )
        flag_patcher.start()
        self.addCleanup(flag_patcher.stop)

        notify_patcher = patch(
            "src.application.use_cases.terraform_crud_handler.NotificationServiceClient"
        )
        self.notifications = notify_patcher.start()
        self.addCleanup(notify_patcher.stop)
        self.notifications.notify_compliance_failure = AsyncMock()
        self.notifications.notify_high_impact = AsyncMock()

        self.validation_svc.generate_and_validate.return_value = _dto(True)
        self.report_svc.generate_report.return_value = _report("low")

    async def _run(self):
        task = await self._handler().handle("create a bucket")
        await task()

    async def test_compliance_violation_locks_and_notifies_compliance_only(self):
        self.compliance_svc.check.return_value = MagicMock(
            passed=False, summary="rule NEB-001 violated"
        )

        await self._run()

        self.set_lock.assert_awaited_once_with(self.ctx.id, True)
        self.notifications.notify_compliance_failure.assert_awaited_once_with(
            self.ctx.id, self.ctx.user_id, "rule NEB-001 violated"
        )
        self.notifications.notify_high_impact.assert_not_awaited()

    async def test_high_impact_locks_and_notifies_high_impact_only(self):
        self.report_svc.generate_report.return_value = _report("high")

        await self._run()

        self.set_lock.assert_awaited_once_with(self.ctx.id, True)
        self.notifications.notify_high_impact.assert_awaited_once_with(
            self.ctx.id, self.ctx.user_id, "high impact detail"
        )
        self.notifications.notify_compliance_failure.assert_not_awaited()

    async def test_both_reasons_lock_once_and_notify_both(self):
        self.compliance_svc.check.return_value = MagicMock(
            passed=False, summary="rule NEB-001 violated"
        )
        self.report_svc.generate_report.return_value = _report("high")

        await self._run()

        self.set_lock.assert_awaited_once_with(self.ctx.id, True)
        self.notifications.notify_compliance_failure.assert_awaited_once()
        self.notifications.notify_high_impact.assert_awaited_once()

    async def test_clean_round_clears_the_lock_without_notifying(self):
        await self._run()

        self.set_lock.assert_awaited_once_with(self.ctx.id, False)
        self.notifications.notify_compliance_failure.assert_not_awaited()
        self.notifications.notify_high_impact.assert_not_awaited()

    async def test_high_impact_is_ignored_when_the_flag_is_off(self):
        self.report_svc.generate_report.return_value = _report("high")

        with patch.object(system_config.orchestration, "block_on_high_impact", False):
            await self._run()

        self.set_lock.assert_awaited_once_with(self.ctx.id, False)
        self.notifications.notify_high_impact.assert_not_awaited()

    async def test_failed_lock_write_raises(self):
        self.set_lock.return_value = False

        task = await self._handler().handle("create a bucket")
        with self.assertRaises(SetLockError):
            await task()


class TestDriftHandlerFlow(_HandlerTestCase):
    def _handler(self) -> TerraformDriftHandler:
        return TerraformDriftHandler(
            session_ctx=self.ctx,
            session_service=self.session_svc,
            template_service=self.template_svc,
            requests_filter_service=self.filter_svc,
            report_service=self.report_svc,
            target_service=self.target_svc,
            drift_service=self.drift_svc,
        )

    async def test_full_round_resolves_drift_unfiltered_on_all_resources(self):
        self.drift_svc.detect_and_resolve_drift.return_value = _dto(True)
        self.template_svc.compose_template.return_value = "conventions"

        task = await self._handler().handle("check drift", is_partial=False)
        await task()

        self.drift_svc.detect_and_resolve_drift.assert_awaited_once_with(
            filter_session_changes=False,
            targets=[],
            conventions="conventions",
            max_iterations=system_config.orchestration.max_drift_reports,
        )
        self.target_svc.generate_drift.assert_not_awaited()
        self.filter_svc.filter.assert_not_awaited()
        self.session_svc.save.assert_awaited_once()

    async def test_partial_round_targets_come_from_drift_target_generator(self):
        self.drift_svc.detect_and_resolve_drift.return_value = _dto(False)
        self.target_svc.generate_drift.return_value = ["module.kvt_001"]

        task = await self._handler().handle("fix the key vault", is_partial=True)
        await task()

        self.target_svc.generate_drift.assert_awaited_once()
        self.assertEqual(
            self.drift_svc.detect_and_resolve_drift.await_args.kwargs["targets"],
            ["module.kvt_001"],
        )
        self.assertFalse(
            self.drift_svc.detect_and_resolve_drift.await_args.kwargs[
                "filter_session_changes"
            ]
        )

    async def test_rejected_partial_request_skips_drift_resolution(self):
        self.filter_svc.filter.return_value = (False, "out of scope")

        task = await self._handler().handle("make me a sandwich", is_partial=True)
        await task()

        self.drift_svc.detect_and_resolve_drift.assert_not_awaited()
        self.session_svc.save.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
