# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for TerraformApplyHandler.

All collaborators are mocked: these cover the background task's
sequencing (next_round → status update → apply → report), the pinned
plan lifecycle (no pin → fail before any apply; the slot is always
discarded when the round ends), the hard-fail path (summarize_problem
awaited, TerraformValidationFailedError raised, no regeneration
collaborators exist to retry with), and that the session is saved
either way.
"""

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from src.application.exceptions import TerraformValidationFailedError
from src.application.use_cases.terraform_apply_handler import TerraformApplyHandler
from src.domains.dto import TerraformValidationDTO
from src.shared.constants import ReportType, SessionStatus


def _dto(validation: bool, plan: str = "apply output") -> TerraformValidationDTO:
    return TerraformValidationDTO(
        validation=validation,
        feedback="" if validation else "boom",
        terraform_plan=plan,
        terraform_targets=[],
    )


class TestTerraformApplyHandler(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.terraform_svc = AsyncMock()
        self.session_svc = AsyncMock()
        self.report_svc = AsyncMock()
        self.template_svc = AsyncMock()
        self.compliance_svc = AsyncMock()
        self.compliance_svc.check.return_value = MagicMock(passed=True)
        self.workspace_svc = MagicMock()
        self.workspace_svc.pinned_plan_path.return_value = Path(
            "/workspaces/sid/pinned/iac/session.plan"
        )
        self.ctx = MagicMock()
        self.handler = TerraformApplyHandler(
            terraform_service=self.terraform_svc,
            session_service=self.session_svc,
            report_service=self.report_svc,
            template_service=self.template_svc,
            session_ctx=self.ctx,
            compliance_service=self.compliance_svc,
            workspace_service=self.workspace_svc,
        )

    async def test_success_applies_pinned_plan_and_generates_report(self):
        self.terraform_svc.apply.return_value = _dto(True)

        task = await self.handler.handle()
        await task()

        self.session_svc.next_round.assert_awaited_once_with("Terraform apply.")
        status_kwargs = self.session_svc.update_status.await_args.kwargs
        self.assertIs(status_kwargs["status"], SessionStatus.APPLY)
        # The pinned plan is applied as-is: no targets, no other args.
        self.terraform_svc.apply.assert_awaited_once_with()
        report_kwargs = self.report_svc.generate_report.await_args.kwargs
        self.assertIs(report_kwargs["type"], ReportType.APPLY)
        self.assertEqual(report_kwargs["content"], "apply output")
        self.compliance_svc.check.assert_awaited_once()
        self.report_svc.summarize_problem.assert_not_awaited()
        self.workspace_svc.discard_pinned.assert_called_once_with(self.ctx.id)
        self.session_svc.save.assert_awaited_once()

    async def test_no_pinned_plan_fails_before_any_apply(self):
        self.workspace_svc.pinned_plan_path.return_value = None

        task = await self.handler.handle()
        with self.assertRaises(TerraformValidationFailedError) as raised:
            await task()

        self.assertIn("pinned", raised.exception.message)
        self.terraform_svc.apply.assert_not_awaited()
        # The round's finally always clears the (here absent) slot.
        self.workspace_svc.discard_pinned.assert_called_once_with(self.ctx.id)
        self.session_svc.save.assert_awaited_once()

    async def test_failure_summarizes_problem_raises_and_consumes_pin(self):
        self.terraform_svc.apply.return_value = _dto(False)
        self.report_svc.summarize_problem.return_value = "apply failed: boom"

        task = await self.handler.handle()
        with self.assertRaises(TerraformValidationFailedError) as raised:
            await task()

        # summarize_problem is async: the message must be its awaited
        # result, not a coroutine object.
        self.report_svc.summarize_problem.assert_awaited_once()
        self.assertEqual(raised.exception.message, "apply failed: boom")
        self.report_svc.generate_report.assert_not_awaited()
        # Hard fail: exactly one apply attempt, and the pin is spent.
        self.terraform_svc.apply.assert_awaited_once_with()
        self.workspace_svc.discard_pinned.assert_called_once_with(self.ctx.id)
        self.session_svc.save.assert_awaited_once()

    async def test_pin_is_consumed_even_when_apply_raises(self):
        self.terraform_svc.apply.side_effect = RuntimeError("service exploded")

        task = await self.handler.handle()
        with self.assertRaises(RuntimeError):
            await task()

        self.workspace_svc.discard_pinned.assert_called_once_with(self.ctx.id)
        self.session_svc.save.assert_awaited_once()

    async def test_apply_runs_after_status_update(self):
        order: list[str] = []
        self.session_svc.update_status.side_effect = lambda **kwargs: (
            order.append("status") or MagicMock()
        )
        self.terraform_svc.apply.side_effect = lambda: (
            order.append("apply") or _dto(True)
        )

        task = await self.handler.handle()
        await task()

        self.assertEqual(order, ["status", "apply"])


if __name__ == "__main__":
    unittest.main()
