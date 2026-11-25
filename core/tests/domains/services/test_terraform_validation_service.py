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


def _imports(failed: list[str]) -> TerraformImportDTO:
    return TerraformImportDTO(
        imported={
            TerraformImportAttempt(
                address="a.ok", resource_id="id-ok", listed_id="id-ok"
            )
        },
        failed={
            TerraformImportAttempt(
                address=a, resource_id=f"id-{a}", listed_id=f"id-{a}", error="boom"
            )
            for a in failed
        },
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
        kwargs.setdefault(
            "max_iterations", system_config.orchestration.max_validation_iteration
        )
        return await self.service.generate_and_validate(
            q="create it",
            ctx=self.ctx,
            conventions=Conventions(templates=[], abbreviations=[]),
            operation_type=OperationType.IMPORT,
            validator=validator,
            **kwargs,
        )

    def __queries(self) -> list[str]:
        return [c.kwargs["query"] for c in self.llm_svc.generate.await_args_list]

    async def test_import_failures_become_the_next_query(self):
        final = _imports([])
        validator = AsyncMock(side_effect=[_imports(["a.bad"]), final])

        result = await self.__run(validator)

        self.assertIs(result, final)
        queries = self.__queries()
        self.assertEqual(queries[0], "create it")
        self.assertEqual(queries[1], _imports(["a.bad"]).feedback)
        self.assertIn("a.bad", queries[1])
        self.assertIn("boom", queries[1])
        # Only the failures are fed back, not what already imported.
        self.assertNotIn("a.ok", queries[1])

    async def test_the_budget_is_the_callers_and_the_last_result_rides_out(self):
        last = _imports(["a.bad"])
        validator = AsyncMock(return_value=last)

        with self.assertRaises(ValidationLoopExceededError) as raised:
            _ = await self.__run(validator, max_iterations=2)

        self.assertEqual(validator.await_count, 2)
        self.assertIs(raised.exception.result, last)

    async def test_the_configured_validation_iterations_bound_the_loop(self):
        validator = AsyncMock(return_value=_plan(False, "nope"))

        with self.assertRaises(ValidationLoopExceededError):
            _ = await self.__run(validator)

        self.assertEqual(
            validator.await_count,
            system_config.orchestration.max_validation_iteration,
        )

    async def test_refine_feedback_rewrites_the_next_query(self):
        validator = AsyncMock(side_effect=[_plan(False, "raw error"), _plan(True)])
        refine = AsyncMock(return_value="1. fix it")

        _ = await self.__run(validator, max_iterations=2, refine_feedback=refine)

        refine.assert_awaited_once_with("raw error")
        self.assertEqual(self.__queries(), ["create it", "1. fix it"])

    async def test_refine_feedback_runs_after_every_failed_attempt(self):
        validator = AsyncMock(return_value=_plan(False, "raw error"))
        refine = AsyncMock(return_value="1. fix it")

        with self.assertRaises(ValidationLoopExceededError):
            _ = await self.__run(validator, max_iterations=2, refine_feedback=refine)

        # Refinement is unconditional, including after the last attempt.
        self.assertEqual(refine.await_count, 2)


class TestTerraformImportDTOValidationResult(unittest.TestCase):
    def test_ok_needs_no_failed_import(self):
        self.assertTrue(_imports([]).ok)
        self.assertFalse(_imports(["a.bad"]).ok)
        self.assertTrue(TerraformImportDTO.empty().ok)

    def test_feedback_lists_one_line_per_failure(self):
        result = _imports(["a.bad", "a.worse"])

        lines = result.feedback.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(line.startswith("- ") for line in lines))
        self.assertEqual(_imports([]).feedback, "")

    def test_stdout_is_the_imported_set_and_targets_are_empty(self):
        result = _imports([])

        self.assertEqual(result.stdout, str(result.imported))
        self.assertIn("a.ok", result.stdout)
        self.assertEqual(TerraformImportDTO.empty().stdout, "")
        self.assertEqual(result.targets, [])


if __name__ == "__main__":
    unittest.main()
