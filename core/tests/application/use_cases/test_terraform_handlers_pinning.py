# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Pin-lifecycle tests for the generate and drift handlers.

All collaborators are mocked; these only assert when the handlers
promote the round's workspace into the session's pinned slot: after a
successful round (the validated plan becomes appliable), and never
after a failed or rejected one.
"""

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.application.exceptions import TerraformValidationFailedError
from src.application.use_cases.terraform_crud_handler import TerraformCRUDHandler
from src.application.use_cases.terraform_drift_handler import TerraformDriftHandler
from src.domains.dto import TerraformValidationDTO
from src.domains.services.database_service import DatabaseService


def _dto(validation: bool) -> TerraformValidationDTO:
    return TerraformValidationDTO(
        validation=validation,
        feedback="" if validation else "boom",
        terraform_plan="plan output",
        terraform_targets=[],
    )


class _PinningTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        lock_patcher = patch.object(
            DatabaseService, "set_lock", AsyncMock(return_value=True)
        )
        lock_patcher.start()
        self.addCleanup(lock_patcher.stop)

        self.session_svc = AsyncMock()
        self.terraform_svc = AsyncMock()
        self.validation_svc = AsyncMock()
        self.template_svc = AsyncMock()
        self.filter_svc = AsyncMock()
        self.filter_svc.filter.return_value = (True, "")
        self.report_svc = AsyncMock()
        self.target_svc = AsyncMock()
        self.target_svc.generate_predictive.return_value = []
        self.drift_svc = AsyncMock()
        self.compliance_svc = AsyncMock()
        self.compliance_svc.check.return_value = MagicMock(passed=True)
        self.workspace_svc = MagicMock()
        self.ctx = MagicMock()
        self.ctx.clone_dir = Path("/workspaces/sid/call-id")


class TestCrudHandlerPinning(_PinningTestCase):
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

    async def test_successful_round_pins_the_workspace(self):
        self.validation_svc.generate_and_validate.return_value = _dto(True)

        task = await self._handler().handle("create a bucket")
        await task()

        self.workspace_svc.pin_workspace.assert_called_once_with(
            self.ctx.id, self.ctx.clone_dir
        )
        self.session_svc.save.assert_awaited_once()

    async def test_failed_validation_does_not_pin(self):
        self.validation_svc.generate_and_validate.return_value = _dto(False)
        self.report_svc.summarize_problem.return_value = "it broke"

        task = await self._handler().handle("create a bucket")
        with self.assertRaises(TerraformValidationFailedError):
            await task()

        self.workspace_svc.pin_workspace.assert_not_called()

    async def test_rejected_request_does_not_pin(self):
        self.filter_svc.filter.return_value = (False, "out of scope")

        task = await self._handler().handle("make me a sandwich")
        await task()

        self.workspace_svc.pin_workspace.assert_not_called()
        self.validation_svc.generate_and_validate.assert_not_awaited()


class TestDriftHandlerPinning(_PinningTestCase):
    def _handler(self) -> TerraformDriftHandler:
        return TerraformDriftHandler(
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

    async def test_fully_remediated_round_pins_the_workspace(self):
        self.drift_svc.detect_and_resolve_drift.return_value = _dto(True)

        task = await self._handler().handle("check drift", is_partial=False)
        await task()

        self.workspace_svc.pin_workspace.assert_called_once_with(
            self.ctx.id, self.ctx.clone_dir
        )

    async def test_unresolved_drift_does_not_pin(self):
        self.drift_svc.detect_and_resolve_drift.return_value = _dto(False)

        task = await self._handler().handle("check drift", is_partial=False)
        await task()

        self.workspace_svc.pin_workspace.assert_not_called()


if __name__ == "__main__":
    unittest.main()
