# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from src.application.services.terraform_drift_service import TerraformDriftService
from src.domains.dto import TerraformDriftDTO, TerraformPlanDTO
from src.domains.value_objects import PlanRef
from src.shared.constants import SessionStatus


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


class TestTerraformDriftService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ctx = MagicMock()
        self.session_svc = AsyncMock()
        self.template_svc = AsyncMock()
        self.validation_svc = AsyncMock()
        self.terraform_svc = AsyncMock()
        self.split_svc = AsyncMock()
        self.artifact_svc = AsyncMock()
        self.targets = TARGETS
        self.conventions = MagicMock()
        self.round_ref = _ref("rev-round")
        self.service = TerraformDriftService(
            session_context=self.ctx,
            session_service=self.session_svc,
            template_service=self.template_svc,
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

    def _statuses(self) -> list[dict]:
        return [call.kwargs for call in self.session_svc.update_status.await_args_list]

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

    async def test_a_failed_initial_plan_returns_without_splitting(self):
        self.terraform_svc.plan.return_value = _plan(None, stdout="partial plan")

        result = await self._run(filter_session_changes=False, plan=None)

        self.assertFalse(result.in_sync)
        self.assertEqual(result.feedback, "Error: plan failed")
        self.assertEqual(result.stdout, "partial plan")
        self.assertIsNone(result.plan)
        self.terraform_svc.drift.assert_not_awaited()
        self.split_svc.split_task.assert_not_awaited()

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

    async def test_a_clean_check_records_the_assessment_and_its_outcome(self):
        self.terraform_svc.drift.return_value = _drift("", self.round_ref)

        await self._run(filter_session_changes=True, plan=self.round_ref)

        calls = self._statuses()
        self.assertEqual(len(calls), 2)
        self.assertIn("Assessing drift", calls[0]["msg"])
        self.assertIn("No drift found", calls[1]["msg"])
        self.assertEqual({c["status"] for c in calls}, {SessionStatus.RECONCILING})

    async def test_the_assessment_is_recorded_before_the_drift_diff_is_stored(self):
        self.terraform_svc.drift.return_value = _drift("[drift]", self.round_ref)
        self.split_svc.split_task.return_value = []
        order: list[str] = []
        self.session_svc.update_status.side_effect = lambda **kw: order.append("status")
        self.artifact_svc.store_terraform_plan.side_effect = lambda **kw: order.append(
            "artifact"
        )

        await self._run(filter_session_changes=False, plan=self.round_ref)

        # The client attaches an artifact to the last status at or before
        # its timestamp, so the diff only renders under this phase if the
        # status is written first.
        self.assertEqual(order[:2], ["status", "artifact"])

    async def test_each_iteration_is_assessed_once(self):
        reconciled = _ref("rev-reconciled")
        self.terraform_svc.drift.side_effect = [
            _drift("[drift]", self.round_ref),
            _drift("", reconciled),
        ]
        self.split_svc.split_task.return_value = [["op a"]]
        self.validation_svc.generate_and_validate.return_value = _plan(reconciled)

        await self._run(
            filter_session_changes=False, max_iterations=3, plan=self.round_ref
        )

        msgs = [c["msg"] for c in self._statuses()]
        self.assertEqual(len([m for m in msgs if "Assessing drift" in m]), 2)
        self.assertIn("No drift found", msgs[-1])

    async def test_unresolved_drift_is_rewritten_by_the_model(self):
        self.terraform_svc.drift.return_value = _drift("[drift]", self.round_ref)
        self.split_svc.split_task.return_value = [["op a"]]
        self.validation_svc.generate_and_validate.return_value = _plan(self.round_ref)

        await self._run(
            filter_session_changes=False, max_iterations=1, plan=self.round_ref
        )

        closing = self._statuses()[-1]
        self.assertIn("issues remain", closing["msg"])
        self.assertIn("[drift]", closing["msg"])
        # A raw terraform diff would be rendered verbatim by the UI.
        self.assertIsNotNone(closing["prompt"])
        self.assertIs(closing["history"], self.ctx.history)

    async def test_the_fixed_literals_cost_no_model_call(self):
        self.terraform_svc.drift.return_value = _drift("", self.round_ref)

        await self._run(filter_session_changes=True, plan=self.round_ref)

        # The pre-check runs on every generate round; paraphrasing a
        # sentence that is already prose would buy nothing.
        for call in self._statuses():
            self.assertIsNone(call.get("prompt"))
        self.template_svc.render.assert_not_awaited()

    async def test_session_owned_drift_is_announced_as_such(self):
        self.terraform_svc.drift.return_value = _drift("[drift]", self.round_ref)
        self.split_svc.split_task.return_value = [["revert sku"]]
        self.split_svc.filter_reconciliation.return_value = []

        await self._run(
            filter_session_changes=True, max_iterations=3, plan=self.round_ref
        )

        closing = self._statuses()[-1]
        self.assertIn("this session's own changes", closing["msg"])

    async def test_an_unreadable_drift_records_no_conclusion(self):
        self.terraform_svc.drift.return_value = _drift(
            "", self.round_ref, feedback="Error: stale plan file"
        )

        await self._run(filter_session_changes=True, plan=self.round_ref)

        # Announcing a phase that then fails is worse than silence: the
        # handler's report and the runner's terminal status carry it.
        calls = self._statuses()
        self.assertEqual(len(calls), 1)
        self.assertIn("Assessing drift", calls[0]["msg"])

    async def test_an_unplannable_workspace_records_only_the_assessment(self):
        self.terraform_svc.plan.return_value = _plan(None, stdout="partial plan")

        await self._run(filter_session_changes=False, plan=None)

        calls = self._statuses()
        self.assertEqual(len(calls), 1)
        self.assertIn("Assessing drift", calls[0]["msg"])


if __name__ == "__main__":
    unittest.main()
