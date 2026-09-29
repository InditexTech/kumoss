# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from src.application.services.terraform_drift_service import TerraformDriftService
from src.domains.dto import FilteredOperationsDTO, TerraformDriftDTO, TerraformPlanDTO
from src.domains.value_objects import PlanRef
from src.shared.constants import OperationType


WORKSPACE = Path("/workspaces/demo")

TARGETS = ["module.kvt_001"]


def _ref(commit: str, stdout: str = "plan output") -> PlanRef:
    return PlanRef(
        workspace=WORKSPACE,
        plan_file="session.plan",
        targets=tuple(TARGETS),
        commit=commit,
        stdout=stdout,
    )


def _plan(plan: PlanRef | None, stdout: str = "plan output") -> TerraformPlanDTO:
    return TerraformPlanDTO(
        ok=plan is not None,
        feedback="" if plan is not None else "Error: plan failed",
        stdout=stdout,
        targets=TARGETS,
        plan=plan,
    )


def _drift(drift: str, plan: PlanRef, feedback: str = "") -> TerraformDriftDTO:
    return TerraformDriftDTO(
        in_sync=not drift and not feedback,
        drift=drift,
        feedback=feedback,
        stdout=plan.stdout,
        plan=plan,
    )


def _filtered(
    kept: list[list[str]],
    excluded: list[str] | None = None,
    explanation: str = "",
) -> FilteredOperationsDTO:
    return FilteredOperationsDTO(
        kept=kept,
        excluded=excluded or [],
        explanation=explanation,
    )


class TestTerraformDriftService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ctx = MagicMock()
        self.validation_svc = AsyncMock()
        self.terraform_svc = AsyncMock()
        self.split_svc = AsyncMock()
        # The exception filter runs on every iteration; unless a test is
        # about it, it lets everything through.
        self.split_svc.filter_exceptions.side_effect = lambda operations: _filtered(
            kept=operations
        )
        self.artifact_svc = AsyncMock()
        self.targets = TARGETS
        self.conventions = MagicMock()
        self.round_ref = _ref("rev-round")
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
        plan: PlanRef | None = None,
    ):
        return await self.service.detect_and_resolve_drift(
            plan=plan,
            filter_session_changes=filter_session_changes,
            targets=self.targets,
            conventions=self.conventions,
            max_iterations=max_iterations,
        )

    def _drift_refs(self) -> list[PlanRef]:
        return [
            call.kwargs["plan"] for call in self.terraform_svc.drift.await_args_list
        ]

    async def test_a_supplied_ref_is_read_without_planning_again(self):
        self.terraform_svc.drift.return_value = _drift("", self.round_ref)

        result = await self._run(filter_session_changes=True, plan=self.round_ref)

        # This is what makes a generate round's pre-check free: the plan
        # it just validated is the one the check reads.
        self.terraform_svc.plan.assert_not_awaited()
        self.assertEqual(self._drift_refs(), [self.round_ref])
        self.assertTrue(result.in_sync)

    async def test_no_ref_plans_before_reading_drift(self):
        fresh = _ref("rev-fresh")
        self.terraform_svc.plan.return_value = _plan(fresh)
        self.terraform_svc.drift.return_value = _drift("", fresh)

        result = await self._run(filter_session_changes=False, plan=None)

        # A dedicated drift session has nothing to start from.
        self.terraform_svc.plan.assert_awaited_once_with(targets=self.targets)
        self.assertEqual(self._drift_refs(), [fresh])
        self.assertTrue(result.in_sync)

    async def test_a_failed_initial_plan_is_split_into_the_fix_query(self):
        fixed = _ref("rev-fixed")
        self.terraform_svc.plan.return_value = _plan(None, stdout="partial plan")
        self.split_svc.split_errors.return_value = "1. declare var.sku"
        self.validation_svc.generate_and_validate.return_value = _plan(fixed)
        self.terraform_svc.drift.return_value = _drift("", fixed)

        result = await self._run(filter_session_changes=False, plan=None)

        self.split_svc.split_errors.assert_awaited_once_with(
            errors="Error: plan failed", operation_type=OperationType.GENERATE
        )
        gen_kwargs = self.validation_svc.generate_and_validate.await_args.kwargs
        self.assertEqual(gen_kwargs["q"], "1. declare var.sku")
        self.assertEqual(
            await gen_kwargs["refine_feedback"]("Error: still broken"),
            "1. declare var.sku",
        )
        self.split_svc.split_errors.assert_awaited_with(
            errors="Error: still broken", operation_type=OperationType.GENERATE
        )
        self.split_svc.split_task.assert_not_awaited()
        self.split_svc.filter_reconciliation.assert_not_awaited()
        self.split_svc.filter_exceptions.assert_not_awaited()
        self.assertEqual(self._drift_refs(), [fixed])
        self.assertTrue(result.in_sync)

    async def test_synchronized_resources_skip_splitting(self):
        self.terraform_svc.drift.return_value = _drift("", self.round_ref)

        result = await self._run(filter_session_changes=True, plan=self.round_ref)

        self.assertTrue(result.in_sync)
        self.split_svc.split_task.assert_not_awaited()
        self.split_svc.filter_reconciliation.assert_not_awaited()
        self.validation_svc.generate_and_validate.assert_not_awaited()

    async def test_unreadable_drift_never_reaches_the_splitter(self):
        self.terraform_svc.drift.return_value = _drift(
            "", self.round_ref, feedback="Error: stale plan file"
        )

        result = await self._run(filter_session_changes=True, plan=self.round_ref)

        # terraform's stderr is not a drift summary: splitting it would
        # turn an engine error into reconciliation operations.
        self.assertFalse(result.in_sync)
        self.assertEqual(result.feedback, "Error: stale plan file")
        self.split_svc.split_task.assert_not_awaited()
        self.validation_svc.generate_and_validate.assert_not_awaited()
        self.artifact_svc.store_terraform_plan.assert_not_awaited()

    async def test_filtered_operations_drive_generation(self):
        self.terraform_svc.drift.return_value = _drift("[drift]", self.round_ref)
        self.split_svc.split_task.return_value = [["revert sku", "add tag"]]
        self.split_svc.filter_reconciliation.return_value = [["add tag"]]
        self.validation_svc.generate_and_validate.return_value = _plan(_ref("rev-gen"))

        await self._run(filter_session_changes=True, plan=self.round_ref)

        self.split_svc.split_task.assert_awaited_once_with(
            task="[drift]", operation_type=OperationType.DRIFT
        )
        self.split_svc.filter_reconciliation.assert_awaited_once_with(
            operations=[["revert sku", "add tag"]]
        )
        self.validation_svc.generate_and_validate.assert_awaited_once()
        kwargs = self.validation_svc.generate_and_validate.await_args.kwargs
        self.assertEqual(kwargs["q"], str(["add tag"]))
        self.assertIs(kwargs["ctx"], self.ctx)
        self.assertIs(kwargs["conventions"], self.conventions)
        self.assertFalse(kwargs["include_forbidden_actions"])

    async def test_validator_plans_the_same_targets(self):
        self.terraform_svc.drift.return_value = _drift("[drift]", self.round_ref)
        self.split_svc.split_task.return_value = [["add tag"]]
        self.split_svc.filter_reconciliation.return_value = [["add tag"]]
        self.validation_svc.generate_and_validate.return_value = _plan(_ref("rev-gen"))

        await self._run(filter_session_changes=True, plan=self.round_ref)

        validator = self.validation_svc.generate_and_validate.await_args.kwargs[
            "validator"
        ]
        self.terraform_svc.plan.reset_mock()
        reads = self.terraform_svc.drift.await_count
        _ = await validator(MagicMock())
        self.terraform_svc.plan.assert_awaited_once_with(targets=self.targets)
        # Reconciliation attempts plan; reading drift is the loop's job.
        self.assertEqual(self.terraform_svc.drift.await_count, reads)

    async def test_all_operations_filtered_stops_without_generating(self):
        self.terraform_svc.drift.return_value = _drift("[drift]", self.round_ref)
        self.split_svc.split_task.return_value = [["revert sku"]]
        self.split_svc.filter_reconciliation.return_value = []

        result = await self._run(
            filter_session_changes=True, max_iterations=3, plan=self.round_ref
        )

        self.assertFalse(result.in_sync)
        self.terraform_svc.drift.assert_awaited_once()
        self.validation_svc.generate_and_validate.assert_not_awaited()

    async def test_unfiltered_mode_generates_every_split_group(self):
        self.terraform_svc.drift.return_value = _drift("[drift]", self.round_ref)
        self.split_svc.split_task.return_value = [["op a"], ["op b"]]
        self.validation_svc.generate_and_validate.return_value = _plan(_ref("rev-gen"))

        await self._run(filter_session_changes=False, plan=self.round_ref)

        self.split_svc.filter_reconciliation.assert_not_awaited()
        self.assertEqual(self.validation_svc.generate_and_validate.await_count, 2)
        queries = [
            call.kwargs["q"]
            for call in self.validation_svc.generate_and_validate.await_args_list
        ]
        self.assertEqual(queries, [str(["op a"]), str(["op b"])])

    async def test_the_last_reconciliation_plan_is_what_the_next_round_reads(self):
        reconciled = _ref("rev-reconciled")
        self.terraform_svc.drift.side_effect = [
            _drift("[drift]", self.round_ref),
            _drift("", reconciled),
        ]
        self.split_svc.split_task.return_value = [["op a"], ["op b"]]
        self.validation_svc.generate_and_validate.side_effect = [
            _plan(_ref("rev-gen-a")),
            _plan(reconciled),
        ]

        result = await self._run(
            filter_session_changes=False, max_iterations=3, plan=self.round_ref
        )

        # Every group re-plans, and the last of those is live enough to
        # read: the loop needs no plan of its own.
        self.terraform_svc.plan.assert_not_awaited()
        self.assertEqual(self._drift_refs(), [self.round_ref, reconciled])
        self.assertTrue(result.in_sync)

    async def test_an_iteration_that_generated_nothing_re_plans(self):
        fresh = _ref("rev-fresh")
        self.terraform_svc.drift.side_effect = [
            _drift("[drift]", self.round_ref),
            _drift("", fresh),
        ]
        self.split_svc.split_task.return_value = []
        self.terraform_svc.plan.return_value = _plan(fresh)

        result = await self._run(
            filter_session_changes=False, max_iterations=2, plan=self.round_ref
        )

        # An iteration with no operations left no plan behind, so the next
        # one plans for itself rather than re-reading a spent artifact and
        # reporting the same drift forever.
        self.terraform_svc.plan.assert_awaited_once_with(targets=self.targets)
        self.assertEqual(self._drift_refs(), [self.round_ref, fresh])
        self.assertTrue(result.in_sync)

    async def test_an_exhausted_budget_reads_what_it_reconciled(self):
        reconciled = _ref("rev-reconciled", stdout="reconciled plan")
        self.terraform_svc.drift.side_effect = [
            _drift("[drift]", self.round_ref),
            _drift("", reconciled),
        ]
        self.split_svc.split_task.return_value = [["op a"]]
        self.validation_svc.generate_and_validate.return_value = _plan(reconciled)

        result = await self._run(
            filter_session_changes=False, max_iterations=1, plan=self.round_ref
        )

        # The last round reconciled with no iteration left to read what it
        # did, so returning the drift from before those changes would
        # report a workspace that no longer exists while apply runs the
        # plan that replaced it.
        self.assertEqual(self._drift_refs(), [self.round_ref, reconciled])
        self.assertTrue(result.in_sync)
        self.assertEqual(result.stdout, "reconciled plan")

    async def test_a_round_that_changed_nothing_is_not_read_twice(self):
        self.terraform_svc.drift.return_value = _drift("[drift]", self.round_ref)
        self.split_svc.split_task.return_value = [["op a"]]
        self.validation_svc.generate_and_validate.return_value = _plan(self.round_ref)

        await self._run(
            filter_session_changes=False, max_iterations=1, plan=self.round_ref
        )

        # Reconciliation that left the workspace on the same fingerprint
        # has nothing new to show, so the closing read is skipped.
        self.assertEqual(self._drift_refs(), [self.round_ref])

    async def test_only_the_drift_report_is_stored(self):
        self.terraform_svc.drift.return_value = _drift("[drift]", self.round_ref)
        self.split_svc.split_task.return_value = [["op a"]]
        self.validation_svc.generate_and_validate.return_value = _plan(_ref("rev-gen"))

        await self._run(filter_session_changes=False, plan=self.round_ref)

        # The plan artifacts are the validation service's to store, one
        # per attempt; this loop only owns the drift report.
        self.artifact_svc.store_terraform_plan.assert_awaited_once()
        kwargs = self.artifact_svc.store_terraform_plan.await_args.kwargs
        self.assertTrue(kwargs["is_drift"])
        self.assertEqual(kwargs["content"], "[drift]")
        self.assertEqual(kwargs["targets"], self.targets)

    async def test_the_exception_filter_runs_after_the_reconciliation_filter(self):
        self.terraform_svc.drift.return_value = _drift("[drift]", self.round_ref)
        self.split_svc.split_task.return_value = [["revert sku", "add tag"]]
        self.split_svc.filter_reconciliation.return_value = [["add tag", "drop kv"]]
        self.split_svc.filter_exceptions.side_effect = None
        self.split_svc.filter_exceptions.return_value = _filtered(
            kept=[["add tag"]],
            excluded=["drop kv"],
            explanation="rule 1 protects the key vault",
        )
        self.validation_svc.generate_and_validate.return_value = _plan(_ref("rev-gen"))

        result = await self._run(filter_session_changes=True, plan=self.round_ref)

        self.split_svc.filter_exceptions.assert_awaited_once_with(
            operations=[["add tag", "drop kv"]]
        )
        self.validation_svc.generate_and_validate.assert_awaited_once()
        kwargs = self.validation_svc.generate_and_validate.await_args.kwargs
        self.assertEqual(kwargs["q"], str(["add tag"]))
        self.assertEqual(result.excluded, ["rule 1 protects the key vault"])

    async def test_the_exception_filter_also_runs_unfiltered(self):
        self.terraform_svc.drift.return_value = _drift("[drift]", self.round_ref)
        self.split_svc.split_task.return_value = [["op a"]]
        self.validation_svc.generate_and_validate.return_value = _plan(_ref("rev-gen"))

        await self._run(filter_session_changes=False, plan=self.round_ref)

        # A full drift round has no session changes to filter, but the
        # exception rules still apply.
        self.split_svc.filter_reconciliation.assert_not_awaited()
        self.split_svc.filter_exceptions.assert_awaited_once_with(operations=[["op a"]])

    async def test_excluding_everything_stops_without_remediating_or_replanning(self):
        self.terraform_svc.drift.return_value = _drift("[drift]", self.round_ref)
        self.split_svc.split_task.return_value = [["drop kv"]]
        self.split_svc.filter_exceptions.side_effect = None
        self.split_svc.filter_exceptions.return_value = _filtered(
            kept=[], excluded=["drop kv"]
        )

        result = await self._run(
            filter_session_changes=False, max_iterations=3, plan=self.round_ref
        )

        # Re-planning would only rediscover the same excluded drift.
        self.validation_svc.generate_and_validate.assert_not_awaited()
        self.terraform_svc.plan.assert_not_awaited()
        self.terraform_svc.drift.assert_awaited_once()
        self.assertFalse(result.in_sync)
        # No explanation from the agent, so the operations stand in for one.
        self.assertEqual(result.excluded, ["drop kv"])

    async def test_exclusions_survive_the_closing_re_read(self):
        reconciled = _ref("rev-reconciled")
        self.terraform_svc.drift.side_effect = [
            _drift("[drift]", self.round_ref),
            _drift("", reconciled),
        ]
        self.split_svc.split_task.return_value = [["add tag", "drop kv"]]
        self.split_svc.filter_exceptions.side_effect = None
        self.split_svc.filter_exceptions.return_value = _filtered(
            kept=[["add tag"]],
            excluded=["drop kv"],
            explanation="rule 1 protects the key vault",
        )
        self.validation_svc.generate_and_validate.return_value = _plan(reconciled)

        result = await self._run(
            filter_session_changes=False, max_iterations=1, plan=self.round_ref
        )

        # The closing read returns a fresh DTO; the exclusions are the
        # loop's own bookkeeping and must be carried onto it.
        self.assertTrue(result.in_sync)
        self.assertEqual(result.excluded, ["rule 1 protects the key vault"])

    async def test_an_iteration_that_excluded_nothing_records_nothing(self):
        self.terraform_svc.drift.return_value = _drift("[drift]", self.round_ref)
        self.split_svc.split_task.return_value = [["op a"]]
        self.validation_svc.generate_and_validate.return_value = _plan(_ref("rev-gen"))

        result = await self._run(filter_session_changes=False, plan=self.round_ref)

        self.assertEqual(result.excluded, [])


if __name__ == "__main__":
    unittest.main()
