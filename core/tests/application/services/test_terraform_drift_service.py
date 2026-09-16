# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from unittest.mock import AsyncMock, MagicMock

from src.application.services.terraform_drift_service import TerraformDriftService
from src.domains.dto import TerraformValidationDTO


def _report(drift: str, targets: list[str]) -> TerraformValidationDTO:
    return TerraformValidationDTO(
        validation=not drift,
        feedback=drift,
        terraform_plan="plan output",
        terraform_targets=targets,
    )


class TestTerraformDriftService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ctx = MagicMock()
        self.validation_svc = AsyncMock()
        self.terraform_svc = AsyncMock()
        self.split_svc = AsyncMock()
        self.artifact_svc = AsyncMock()
        self.targets = ["module.kvt_001"]
        self.conventions = MagicMock()
        self.service = TerraformDriftService(
            session_context=self.ctx,
            validation_service=self.validation_svc,
            terraform_service=self.terraform_svc,
            split_service=self.split_svc,
            artifact_service=self.artifact_svc,
        )

    async def _run(
        self,
        filter_session_changes: bool,
        max_iterations: int = 1,
        prev_validation: TerraformValidationDTO | None = None,
    ):
        return await self.service.detect_and_resolve_drift(
            filter_session_changes=filter_session_changes,
            targets=self.targets,
            conventions=self.conventions,
            max_iterations=max_iterations,
            prev_validation=prev_validation,
        )

    async def test_synchronized_resources_skip_splitting(self):
        self.terraform_svc.validate.return_value = _report("", self.targets)

        result = await self._run(filter_session_changes=True)

        self.assertTrue(result.validation)
        self.split_svc.split_task.assert_not_awaited()
        self.split_svc.filter_reconciliation.assert_not_awaited()
        self.validation_svc.generate_and_validate.assert_not_awaited()

    async def test_filtered_operations_drive_generation(self):
        self.terraform_svc.validate.return_value = _report("[drift]", self.targets)
        self.split_svc.split_task.return_value = [["revert sku", "add tag"]]
        self.split_svc.filter_reconciliation.return_value = [["add tag"]]

        await self._run(filter_session_changes=True)

        self.split_svc.split_task.assert_awaited_once_with(task="[drift]")
        self.split_svc.filter_reconciliation.assert_awaited_once_with(
            operations=[["revert sku", "add tag"]]
        )
        self.validation_svc.generate_and_validate.assert_awaited_once()
        kwargs = self.validation_svc.generate_and_validate.await_args.kwargs
        self.assertEqual(kwargs["q"], str(["add tag"]))
        self.assertIs(kwargs["ctx"], self.ctx)
        self.assertIs(kwargs["conventions"], self.conventions)
        self.assertFalse(kwargs["include_forbidden_actions"])

    async def test_validator_plans_the_same_targets_without_drift(self):
        self.terraform_svc.validate.return_value = _report("[drift]", self.targets)
        self.split_svc.split_task.return_value = [["add tag"]]
        self.split_svc.filter_reconciliation.return_value = [["add tag"]]

        await self._run(filter_session_changes=True)

        validator = self.validation_svc.generate_and_validate.await_args.kwargs[
            "validator"
        ]
        self.terraform_svc.validate.reset_mock()
        await validator(MagicMock())
        self.terraform_svc.validate.assert_awaited_once_with(
            targets=self.targets, get_drift=False
        )

    async def test_all_operations_filtered_stops_without_generating(self):
        self.terraform_svc.validate.return_value = _report("[drift]", self.targets)
        self.split_svc.split_task.return_value = [["revert sku"]]
        self.split_svc.filter_reconciliation.return_value = []

        result = await self._run(filter_session_changes=True, max_iterations=3)

        self.assertFalse(result.validation)
        self.terraform_svc.validate.assert_awaited_once()
        self.validation_svc.generate_and_validate.assert_not_awaited()

    async def test_unfiltered_mode_generates_every_split_group(self):
        self.terraform_svc.validate.return_value = _report("[drift]", self.targets)
        self.split_svc.split_task.return_value = [["op a"], ["op b"]]

        await self._run(filter_session_changes=False)

        self.split_svc.filter_reconciliation.assert_not_awaited()
        self.assertEqual(self.validation_svc.generate_and_validate.await_count, 2)
        queries = [
            call.kwargs["q"]
            for call in self.validation_svc.generate_and_validate.await_args_list
        ]
        self.assertEqual(queries, [str(["op a"]), str(["op b"])])

    async def test_iterates_until_drift_is_resolved(self):
        self.terraform_svc.validate.side_effect = [
            _report("[drift]", self.targets),
            _report("", self.targets),
        ]
        self.split_svc.split_task.return_value = [["op a"]]

        result = await self._run(filter_session_changes=False, max_iterations=3)

        self.assertTrue(result.validation)
        self.assertEqual(self.terraform_svc.validate.await_count, 2)
        self.validation_svc.generate_and_validate.assert_awaited_once()

    async def test_stores_drift_report_then_plan_so_plan_is_latest(self):
        self.terraform_svc.validate.return_value = _report("[drift]", self.targets)
        self.split_svc.split_task.return_value = [["op a"]]

        await self._run(filter_session_changes=False)

        flags = [
            call.kwargs["is_drift"]
            for call in self.artifact_svc.store_terraform_plan.await_args_list
        ]
        self.assertEqual(flags, [True, False])

    async def test_clean_prev_validation_returns_untouched_without_planning(self):
        prev = _report("", self.targets)

        result = await self._run(filter_session_changes=True, prev_validation=prev)

        self.assertIs(result, prev)
        self.terraform_svc.validate.assert_not_awaited()
        self.artifact_svc.store_terraform_plan.assert_not_awaited()
        self.split_svc.split_task.assert_not_awaited()

    async def test_seeded_prev_validation_defers_the_plan_to_the_next_iteration(self):
        prev = _report("[seeded drift]", self.targets)
        self.terraform_svc.validate.return_value = _report("", self.targets)
        self.split_svc.split_task.return_value = [["revert sku"]]

        result = await self._run(
            filter_session_changes=False, max_iterations=2, prev_validation=prev
        )

        self.split_svc.split_task.assert_awaited_once_with(task="[seeded drift]")
        self.terraform_svc.validate.assert_awaited_once_with(
            targets=self.targets, get_drift=True
        )
        self.assertTrue(result.validation)


if __name__ == "__main__":
    unittest.main()
