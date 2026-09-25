# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for TerraformValidationService.generate_and_validate.

The loop is validator-agnostic: a plan and an import round both answer
with ok, feedback, stdout and targets, so whichever validator runs, its
feedback becomes the next generation query and its result is what the
loop hands back, or carries out when it gives up.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock

from src.domains.dto import (
    TerraformImportAttempt,
    TerraformImportDTO,
    TerraformPlanDTO,
    ToolResultDTO,
)
from src.domains.exceptions import ValidationLoopExceededError
from src.domains.services.terraform_validation_service import (
    TerraformValidationService,
)
from src.domains.value_objects import Conventions
from src.shared.config import system_config
from src.shared.constants import OperationType


def _plan(ok: bool, feedback: str = "") -> TerraformPlanDTO:
    return TerraformPlanDTO(
        ok=ok, feedback=feedback, stdout="", targets=["a.b"], plan=None
    )


def _imports(failed: list[str], plan: TerraformPlanDTO) -> TerraformImportDTO:
    return TerraformImportDTO(
        imported=[TerraformImportAttempt(address="a.ok", resource_id="id-ok")],
        failed=[
            TerraformImportAttempt(address=a, resource_id=f"id-{a}", error="boom")
            for a in failed
        ],
        plan_result=plan,
    )


class TestGenerateAndValidate(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.git = AsyncMock()
        self.git.get_changed_files.return_value = []
        self.git.get_untracked_files.return_value = []
        self.llm_svc = AsyncMock()
        self.llm_svc.generate.return_value = ToolResultDTO(
            name="task_complete",
            tool_call_id="call-1",
            success=True,
            result={"summary": "done"},
        )
        self.ctx = MagicMock()
        self.service = TerraformValidationService(
            git=self.git,
            files=MagicMock(),
            session_service=AsyncMock(),
            template_service=AsyncMock(),
            llm_service=self.llm_svc,
            tool_orchestration_service=MagicMock(),
            artifact_service=AsyncMock(),
        )

    async def __run(self, validator: AsyncMock, **kwargs):
        return await self.service.generate_and_validate(
            q="create it",
            ctx=self.ctx,
            conventions=Conventions(templates=[], abbreviations=[]),
            include_forbidden_actions=False,
            operation_type=OperationType.IMPORT,
            validator=validator,
            **kwargs,
        )

    def __queries(self) -> list[str]:
        return [c.kwargs["query"] for c in self.llm_svc.generate.await_args_list]

    async def test_import_failures_become_the_next_query(self):
        final = _imports([], _plan(True))
        validator = AsyncMock(side_effect=[_imports(["a.bad"], _plan(True)), final])

        result = await self.__run(validator)

        self.assertIs(result, final)
        queries = self.__queries()
        self.assertEqual(queries[0], "create it")
        self.assertIn("`a.bad` (id-a.bad): boom", queries[1])
        self.assertIn("`a.ok` (id-ok)", queries[1])

    async def test_a_failed_plan_is_fed_back_before_any_import_error(self):
        validator = AsyncMock(
            side_effect=[
                _imports(["a.bad"], _plan(False, "plan stderr")),
                _imports([], _plan(True)),
            ]
        )

        _ = await self.__run(validator)

        self.assertEqual(self.__queries()[1], "plan stderr")

    async def test_the_budget_is_the_callers_and_the_last_result_rides_out(self):
        last = _imports(["a.bad"], _plan(True))
        validator = AsyncMock(return_value=last)

        with self.assertRaises(ValidationLoopExceededError) as raised:
            _ = await self.__run(validator, max_iterations=2)

        self.assertEqual(validator.await_count, 2)
        self.assertIs(raised.exception.result, last)

    async def test_the_budget_defaults_to_the_validation_iterations(self):
        validator = AsyncMock(return_value=_plan(False, "nope"))

        with self.assertRaises(ValidationLoopExceededError):
            _ = await self.__run(validator)

        self.assertEqual(
            validator.await_count,
            system_config.orchestration.max_validation_iteration,
        )


class TestTerraformImportDTOValidationResult(unittest.TestCase):
    def test_ok_needs_a_passing_plan_and_no_failed_import(self):
        self.assertTrue(_imports([], _plan(True)).ok)
        self.assertFalse(_imports(["a.bad"], _plan(True)).ok)
        self.assertFalse(_imports([], _plan(False, "x")).ok)

    def test_stdout_and_targets_are_the_plans(self):
        plan = TerraformPlanDTO(
            ok=True, feedback="", stdout="plan text", targets=["x.y"], plan=None
        )
        result = _imports([], plan)

        self.assertEqual(result.stdout, "plan text")
        self.assertEqual(result.targets, ["x.y"])
        self.assertEqual(result.feedback, "")


if __name__ == "__main__":
    unittest.main()
