# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Terraform (raw-op orchestration).

The generated client op modules are mocked, so no IaC service is
needed: these cover the three verbs over the plan artifact — ``plan``
sequencing init → validate → plan and returning a ref to what it wrote
(with the per-instance init cache: skip after first success, re-init and
retry once on an init-shaped failure), ``drift`` reading a ref back with
a lone ``show``, re-planning a ref the workspace has moved past and
refusing one from another workspace, and ``apply`` as a single job on
the session plan artifact. Also the validation boolean and drift parsing
owned by the core, and the mapping of the two failure planes — a
succeeded job with a non-zero exit_code maps to a DTO with ok=False,
while failed/lost/rejected jobs raise ExceptionHandler with the
equivalent HTTP code.
"""

import json
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.clients.iac.models.job import Job
from src.clients.iac.models.job_accepted import JobAccepted
from src.clients.iac.models.job_kind import JobKind
from src.clients.iac.models.job_status import JobStatus
from src.clients.iac.models.operation_result import OperationResult
from src.clients.iac.models.problem import Problem
from src.domains.interfaces.git_interface import IGit
from src.domains.services.tracer_service import TracerService
from src.domains.value_objects import PlanRef
from src.infrastructure.terraform import terraform as tv
from src.infrastructure.terraform.backend import TerraformBackend
from src.shared.config.system_config import IacServiceConfig
from src.shared.constants import TerraformProvider
from src.shared.exceptions import ExceptionHandler


# Mirrors paths.session_plan_filename in the patched system_config below.
SESSION_PLAN_FILENAME = "session.plan"

# Truthy so __ensure_init lands the backend in the workspace before init.
STATE_BUCKET = "nebula-state"

SCOPE_ID = "sub-uuid-1234"
TERRAFORM_PROVIDER = TerraformProvider.AZURE

WORKSPACE = Path("/workspaces/demo")

# Workspace fingerprints: what the git double reports, and one that
# stands for a tree that has moved since a plan was produced.
REVISION = "a" * 64
STALE_REVISION = "b" * 64


NO_CHANGES_PLAN_JSON = json.dumps({"format_version": "1.2", "resource_changes": []})

DRIFTED_PLAN_JSON = json.dumps(
    {
        "format_version": "1.2",
        "resource_changes": [
            {
                "address": "azurerm_resource_group.main",
                "change": {
                    "actions": ["update"],
                    "before": {"tags": {"env": "prod"}},
                    "after": {"tags": {"env": "dev"}},
                },
            }
        ],
    }
)

INIT_REQUIRED_STDERR = (
    'Error: Missing required provider\n\nPlease run "terraform init".'
)


def _ok(stdout: str = "", stderr: str = "") -> OperationResult:
    return OperationResult(exit_code=0, stdout=stdout, stderr=stderr)


def _failed_cmd(stderr: str, stdout: str = "") -> OperationResult:
    return OperationResult(exit_code=1, stdout=stdout, stderr=stderr)


def _ref(
    targets: tuple[str, ...] = (),
    commit: str = REVISION,
    stdout: str = "plan output",
    workspace: Path = WORKSPACE,
    plan_file: str = SESSION_PLAN_FILENAME,
) -> PlanRef:
    return PlanRef(
        workspace=workspace,
        plan_file=plan_file,
        targets=targets,
        commit=commit,
        stdout=stdout,
    )


def _job(status: JobStatus, kind: JobKind, result=None, error=None) -> Job:
    now = datetime.now(timezone.utc)
    return Job(
        job_id=uuid.uuid4(),
        kind=kind,
        status=status,
        created_at=now,
        started_at=None if status is JobStatus.QUEUED else now,
        finished_at=now if status in (JobStatus.SUCCEEDED, JobStatus.FAILED) else None,
        result=result,
        error=error,
    )


class _TerraformTestCase(unittest.IsolatedAsyncioTestCase):
    """Shared fixtures: tracer mock, git double, config patch, op patching."""

    def setUp(self):
        tracer_patcher = patch.object(
            TracerService, "get_current_tracer", return_value=MagicMock()
        )
        tracer_patcher.start()
        self.addCleanup(tracer_patcher.stop)

        self.backend = MagicMock(spec=TerraformBackend)
        self.backend.apply.return_value = True
        self.git = AsyncMock(spec=IGit)
        self.git.get_workspace_revision.return_value = REVISION
        self.terraform = self._make_terraform()

    def _make_terraform(self) -> tv.Terraform:
        return tv.Terraform(
            workspace_path=WORKSPACE,
            git=self.git,
            scope_id=SCOPE_ID,
            terraform_provider=TERRAFORM_PROVIDER,
            backend=self.backend,
        )

    def _use_config(self, **overrides) -> IacServiceConfig:
        cfg = IacServiceConfig(
            endpoint="http://iac.test:8082",
            token_env="",
            timeout=1.0,
            job_poll_interval=0.0,
            **overrides,
        )
        patcher = patch.object(
            tv,
            "system_config",
            SimpleNamespace(
                services=SimpleNamespace(iac=cfg),
                paths=SimpleNamespace(session_plan_filename=SESSION_PLAN_FILENAME),
                storage=SimpleNamespace(state_bucket=STATE_BUCKET),
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return cfg

    def _patch_ops(self, **outcomes) -> tuple[dict[str, AsyncMock], AsyncMock]:
        """Patch the five op modules and the job poll.

        ``outcomes`` maps op name (init/validate/plan/show/apply) to one
        outcome or a list of per-submission outcomes, each being either
        an OperationResult (the op's job succeeds with it), a Job (the
        poll returns it verbatim), or a non-JobAccepted submit response
        (Problem / None). Ops without an outcome — or submitted more
        times than they have outcomes — fail the test.
        """
        jobs_by_id: dict[uuid.UUID, Job] = {}
        submit_mocks: dict[str, AsyncMock] = {}
        for name, module in (
            ("init", tv.init_op),
            ("validate", tv.validate_op),
            ("plan", tv.plan_op),
            ("show", tv.show_op),
            ("apply", tv.apply_op),
        ):
            if name not in outcomes:
                mock = AsyncMock(
                    side_effect=AssertionError(f"{name} op should not be submitted")
                )
            else:
                queue = outcomes[name]
                pending = list(queue) if isinstance(queue, (list, tuple)) else [queue]

                def submit(*, client, body, _name=name, _pending=pending):
                    if not _pending:
                        raise AssertionError(
                            f"{_name} op submitted more times than expected"
                        )
                    outcome = _pending.pop(0)
                    if isinstance(outcome, OperationResult):
                        outcome = _job(
                            JobStatus.SUCCEEDED, kind=JobKind(_name), result=outcome
                        )
                    if isinstance(outcome, Job):
                        job_id = uuid.uuid4()
                        jobs_by_id[job_id] = outcome
                        return JobAccepted(job_id=job_id, status=JobStatus.QUEUED)
                    # Rejected submission: Problem / None straight back.
                    return outcome

                mock = AsyncMock(side_effect=submit)
            submit_mocks[name] = mock
            patcher = patch.object(module, "asyncio", mock)
            patcher.start()
            self.addCleanup(patcher.stop)

        async def poll(job_id, client):
            return jobs_by_id[job_id]

        poll_mock = AsyncMock(side_effect=poll)
        patcher = patch.object(tv.get_job_op, "asyncio", poll_mock)
        patcher.start()
        self.addCleanup(patcher.stop)
        return submit_mocks, poll_mock


class TestTerraformPlan(_TerraformTestCase):
    async def test_all_ops_succeed_and_a_ref_names_the_artifact(self):
        self._use_config()
        submit_mocks, _ = self._patch_ops(
            init=_ok(),
            validate=_ok(),
            plan=_ok(stdout="plan output"),
        )

        dto = await self.terraform.plan(targets=["module.db"])

        self.assertTrue(dto.ok)
        self.assertEqual(dto.feedback, "")
        self.assertEqual(dto.stdout, "plan output")
        self.assertEqual(dto.targets, ["module.db"])
        self.assertEqual(
            dto.plan,
            _ref(targets=("module.db",), commit=REVISION),
        )
        # The plan text rides with the ref, for whoever reads its drift.
        assert dto.plan is not None
        self.assertEqual(dto.plan.stdout, "plan output")

        init_body = submit_mocks["init"].await_args.kwargs["body"]
        self.assertEqual(init_body.workspace_path, "/workspaces/demo")
        # The state backend lands in the workspace before init reads it.
        self.backend.apply.assert_called_once_with(WORKSPACE)
        plan_body = submit_mocks["plan"].await_args.kwargs["body"]
        self.assertEqual(plan_body.targets, ["module.db"])
        self.assertEqual(plan_body.plan_file, SESSION_PLAN_FILENAME)
        # The IaC contract restricts plan_file to a single path segment.
        self.assertRegex(plan_body.plan_file, r"^[A-Za-z0-9._-]{1,128}$")

    async def test_the_revision_is_sampled_after_the_plan_job(self):
        self._use_config()
        submit_mocks, _ = self._patch_ops(
            init=_ok(),
            validate=_ok(),
            plan=_ok(stdout="plan output"),
        )
        plan_awaits: list[int] = []

        async def revision() -> str:
            plan_awaits.append(submit_mocks["plan"].await_count)
            return REVISION

        self.git.get_workspace_revision.side_effect = revision

        dto = await self.terraform.plan(targets=[])

        self.assertTrue(dto.ok)
        # Sampling before the plan job would fingerprint a workspace
        # without the plan file `plan -out` is about to write, so the ref
        # could never match its own workspace at drift time.
        self.assertEqual(plan_awaits, [1])

    async def test_init_failure_returns_no_ref(self):
        self._use_config()
        self._patch_ops(init=_failed_cmd("Error: backend init failed"))

        dto = await self.terraform.plan(targets=["module.db"])

        self.assertFalse(dto.ok)
        self.assertEqual(dto.feedback, "Error: backend init failed")
        self.assertEqual(dto.stdout, "")
        self.assertEqual(dto.targets, ["module.db"])
        self.assertIsNone(dto.plan)

    async def test_validate_failure_returns_no_ref(self):
        self._use_config()
        self._patch_ops(
            init=_ok(),
            validate=_failed_cmd("Error: invalid resource block"),
        )

        dto = await self.terraform.plan(targets=["module.db"])

        self.assertFalse(dto.ok)
        self.assertEqual(dto.feedback, "Error: invalid resource block")
        self.assertEqual(dto.stdout, "")
        self.assertIsNone(dto.plan)

    async def test_plan_failure_keeps_stdout_but_has_no_ref(self):
        self._use_config()
        submit_mocks, _ = self._patch_ops(
            init=_ok(),
            validate=_ok(),
            plan=_failed_cmd("Error: auth", stdout="partial plan"),
        )

        dto = await self.terraform.plan(targets=[])

        self.assertFalse(dto.ok)
        self.assertEqual(dto.feedback, "Error: auth")
        # The failed plan's output is still worth storing as an artifact,
        # but there is no file for anyone to read back.
        self.assertEqual(dto.stdout, "partial plan")
        self.assertIsNone(dto.plan)
        # A non-init failure must not trigger the re-init retry.
        self.assertEqual(submit_mocks["init"].await_count, 1)
        self.assertEqual(submit_mocks["plan"].await_count, 1)

    async def test_failed_job_raises_502_with_problem_detail(self):
        self._use_config()
        error = Problem(
            title="Internal Server Error", status=500, detail="Key Vault unreachable"
        )
        self._patch_ops(
            init=_job(JobStatus.FAILED, kind=JobKind.INIT, error=error),
        )

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.terraform.plan(targets=[])
        self.assertEqual(ctx.exception.error_code, 502)
        self.assertIn("Key Vault unreachable", ctx.exception.message)

    async def test_job_budget_exhausted_raises_504(self):
        self._use_config(job_timeout=0.0)
        self._patch_ops(init=_job(JobStatus.RUNNING, kind=JobKind.INIT))

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.terraform.plan(targets=[])
        self.assertEqual(ctx.exception.error_code, 504)

    async def test_submit_rejection_raises_502(self):
        for rejected in (
            Problem(title="Service Unavailable", status=503),
            None,
        ):
            with self.subTest(rejected=rejected):
                self._use_config()
                self._patch_ops(init=rejected)
                self.terraform = self._make_terraform()

                with self.assertRaises(ExceptionHandler) as ctx:
                    await self.terraform.plan(targets=[])
                self.assertEqual(ctx.exception.error_code, 502)

    async def test_poll_problem_raises_502(self):
        self._use_config()
        self._patch_ops(init=_ok())
        poll_mock = AsyncMock(
            return_value=Problem(title="Not Found", status=404, detail="Unknown job")
        )
        patcher = patch.object(tv.get_job_op, "asyncio", poll_mock)
        patcher.start()
        self.addCleanup(patcher.stop)

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.terraform.plan(targets=[])
        self.assertEqual(ctx.exception.error_code, 502)
        self.assertIn("lost or rejected", ctx.exception.message)

    async def test_missing_result_on_succeeded_job_raises_502(self):
        self._use_config()
        self._patch_ops(
            init=_job(JobStatus.SUCCEEDED, kind=JobKind.INIT, result=None),
        )

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.terraform.plan(targets=[])
        self.assertEqual(ctx.exception.error_code, 502)


class TestTerraformDrift(_TerraformTestCase):
    async def test_drift_reads_the_rounds_plan_without_planning_again(self):
        self._use_config()
        submit_mocks, _ = self._patch_ops(
            init=_ok(),
            validate=_ok(),
            plan=_ok(stdout="round plan"),
            show=_ok(stdout=DRIFTED_PLAN_JSON),
        )

        round_result = await self.terraform.plan(targets=["module.db"])
        assert round_result.plan is not None
        drift = await self.terraform.drift(plan=round_result.plan)

        # The round's plan is the only one: the pre-check adds no init,
        # no validate and no plan, just the show it needs.
        self.assertEqual(submit_mocks["init"].await_count, 1)
        self.assertEqual(submit_mocks["validate"].await_count, 1)
        self.assertEqual(submit_mocks["plan"].await_count, 1)
        submit_mocks["show"].assert_awaited_once()

        self.assertFalse(drift.in_sync)
        self.assertEqual(drift.feedback, "")
        self.assertEqual(drift.stdout, "round plan")
        self.assertEqual(drift.plan, round_result.plan)

        show_body = submit_mocks["show"].await_args.kwargs["body"]
        self.assertEqual(show_body.workspace_path, "/workspaces/demo")
        self.assertEqual(show_body.plan_file, SESSION_PLAN_FILENAME)

    async def test_drift_is_parsed_and_inverted(self):
        self._use_config()
        self._patch_ops(init=_ok(), show=_ok(stdout=DRIFTED_PLAN_JSON))

        result = await self.terraform.drift(plan=_ref())

        self.assertFalse(result.in_sync)
        self.assertEqual(result.feedback, "")
        drift = json.loads(result.drift)
        self.assertEqual(len(drift), 1)
        self.assertEqual(drift[0]["address"], "azurerm_resource_group.main")
        self.assertEqual(drift[0]["action"], "update resource")
        # reversed=True swaps old/new so the summary reads as "what to
        # change to get back in sync" rather than what the plan would do.
        self.assertEqual(
            drift[0]["changes"]["values_changed"]["root['tags']['env']"],
            {"old_value": "dev", "new_value": "prod"},
        )

    async def test_a_clean_plan_is_in_sync(self):
        self._use_config()
        self._patch_ops(init=_ok(), show=_ok(stdout=NO_CHANGES_PLAN_JSON))

        result = await self.terraform.drift(plan=_ref(stdout="plan output"))

        self.assertTrue(result.in_sync)
        self.assertEqual(result.drift, "")
        self.assertEqual(result.feedback, "")
        self.assertEqual(result.stdout, "plan output")

    async def test_the_ref_decides_which_artifact_is_read(self):
        self._use_config()
        submit_mocks, _ = self._patch_ops(
            init=_ok(), show=_ok(stdout=NO_CHANGES_PLAN_JSON)
        )

        _ = await self.terraform.drift(plan=_ref(plan_file="reconcile.plan"))

        show_body = submit_mocks["show"].await_args.kwargs["body"]
        self.assertEqual(show_body.plan_file, "reconcile.plan")

    async def test_a_stale_ref_is_re_planned_before_its_drift_is_read(self):
        self._use_config()
        submit_mocks, _ = self._patch_ops(
            init=_ok(),
            validate=_ok(),
            plan=_ok(stdout="fresh plan"),
            show=_ok(stdout=NO_CHANGES_PLAN_JSON),
        )

        result = await self.terraform.drift(
            plan=_ref(
                targets=("module.db",), commit=STALE_REVISION, stdout="stale plan"
            )
        )

        # Self-healing rather than fail-fast: the ref guards a best-effort
        # optimization, so a caller that held one too long still gets an
        # answer — read from the new plan, for the ref's own targets.
        submit_mocks["plan"].assert_awaited_once()
        self.assertEqual(
            submit_mocks["plan"].await_args.kwargs["body"].targets, ["module.db"]
        )
        self.assertTrue(result.in_sync)
        self.assertEqual(result.stdout, "fresh plan")
        self.assertEqual(result.plan, _ref(targets=("module.db",), commit=REVISION))

    async def test_a_stale_ref_whose_re_plan_fails_reports_the_failure(self):
        self._use_config()
        self._patch_ops(
            init=_ok(),
            validate=_ok(),
            plan=_failed_cmd("Error: auth", stdout="partial plan"),
        )

        result = await self.terraform.drift(plan=_ref(commit=STALE_REVISION))

        self.assertFalse(result.in_sync)
        self.assertEqual(result.drift, "")
        self.assertEqual(result.feedback, "Error: auth")
        self.assertEqual(result.stdout, "partial plan")
        self.assertIsNone(result.plan)

    async def test_a_ref_from_another_workspace_raises_500(self):
        self._use_config()
        self._patch_ops()

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.terraform.drift(plan=_ref(workspace=Path("/workspaces/other")))
        self.assertEqual(ctx.exception.error_code, 500)
        self.assertIn("another workspace", ctx.exception.message)

    async def test_show_failure_is_reported_as_feedback_not_drift(self):
        self._use_config()
        self._patch_ops(init=_ok(), show=_failed_cmd("Error: stale plan file"))

        result = await self.terraform.drift(plan=_ref(stdout="plan output"))

        # Keeping stderr out of `drift` is what stops terraform's error
        # output from reaching the task splitter as though it were drift.
        self.assertFalse(result.in_sync)
        self.assertEqual(result.drift, "")
        self.assertEqual(result.feedback, "Error: stale plan file")
        self.assertEqual(result.stdout, "plan output")
        self.assertIsNone(result.plan)

    async def test_init_failure_is_reported_as_feedback(self):
        self._use_config()
        self._patch_ops(init=_failed_cmd("Error: backend init failed"))

        result = await self.terraform.drift(plan=_ref(stdout="plan output"))

        self.assertFalse(result.in_sync)
        self.assertEqual(result.drift, "")
        self.assertEqual(result.feedback, "Error: backend init failed")
        self.assertIsNone(result.plan)

    async def test_show_reinits_once_when_init_is_required(self):
        self._use_config()
        submit_mocks, _ = self._patch_ops(
            init=[_ok(), _ok()],
            show=[
                _failed_cmd(INIT_REQUIRED_STDERR),
                _ok(stdout=NO_CHANGES_PLAN_JSON),
            ],
        )

        result = await self.terraform.drift(plan=_ref())

        # A workspace that lost its .terraform/ still re-inits once.
        self.assertTrue(result.in_sync)
        self.assertEqual(submit_mocks["init"].await_count, 2)
        self.assertEqual(submit_mocks["show"].await_count, 2)

    async def test_unparseable_show_json_raises_502(self):
        self._use_config()
        self._patch_ops(init=_ok(), show=_ok(stdout="not json"))

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.terraform.drift(plan=_ref())
        self.assertEqual(ctx.exception.error_code, 502)


class TestTerraformInitCache(_TerraformTestCase):
    async def test_init_runs_once_across_two_plans(self):
        self._use_config()
        submit_mocks, _ = self._patch_ops(
            init=_ok(),
            validate=[_ok(), _ok()],
            plan=[_ok(stdout="first"), _ok(stdout="second")],
        )

        first = await self.terraform.plan(targets=[])
        second = await self.terraform.plan(targets=[])

        self.assertTrue(first.ok)
        self.assertTrue(second.ok)
        self.assertEqual(submit_mocks["init"].await_count, 1)
        self.assertEqual(submit_mocks["validate"].await_count, 2)
        self.assertEqual(submit_mocks["plan"].await_count, 2)

    async def test_failed_init_is_retried_on_the_next_plan(self):
        self._use_config()
        submit_mocks, _ = self._patch_ops(
            init=[_failed_cmd("Error: backend init failed"), _ok()],
            validate=_ok(),
            plan=_ok(stdout="plan output"),
        )

        first = await self.terraform.plan(targets=[])
        second = await self.terraform.plan(targets=[])

        self.assertFalse(first.ok)
        self.assertTrue(second.ok)
        self.assertEqual(submit_mocks["init"].await_count, 2)

    async def test_init_shaped_failure_reinits_and_retries_once(self):
        self._use_config()
        submit_mocks, _ = self._patch_ops(
            init=[_ok(), _ok()],
            validate=_ok(),
            plan=[_failed_cmd(INIT_REQUIRED_STDERR), _ok(stdout="plan output")],
        )

        dto = await self.terraform.plan(targets=[])

        self.assertTrue(dto.ok)
        self.assertEqual(dto.stdout, "plan output")
        self.assertEqual(submit_mocks["init"].await_count, 2)
        self.assertEqual(submit_mocks["plan"].await_count, 2)

    async def test_second_init_shaped_failure_is_returned(self):
        self._use_config()
        submit_mocks, _ = self._patch_ops(
            init=[_ok(), _ok()],
            validate=_ok(),
            plan=[
                _failed_cmd(INIT_REQUIRED_STDERR),
                _failed_cmd(INIT_REQUIRED_STDERR),
            ],
        )

        dto = await self.terraform.plan(targets=[])

        self.assertFalse(dto.ok)
        self.assertEqual(dto.feedback, INIT_REQUIRED_STDERR)
        self.assertIsNone(dto.plan)
        self.assertEqual(submit_mocks["init"].await_count, 2)
        self.assertEqual(submit_mocks["plan"].await_count, 2)

    async def test_failed_reinit_is_returned_as_init_failure(self):
        self._use_config()
        submit_mocks, _ = self._patch_ops(
            init=[_ok(), _failed_cmd("Error: backend init failed")],
            validate=_ok(),
            plan=_failed_cmd(INIT_REQUIRED_STDERR),
        )

        dto = await self.terraform.plan(targets=[])

        self.assertFalse(dto.ok)
        self.assertEqual(dto.feedback, "Error: backend init failed")
        self.assertEqual(submit_mocks["init"].await_count, 2)
        self.assertEqual(submit_mocks["plan"].await_count, 1)


class TestTerraformApply(_TerraformTestCase):
    async def test_apply_is_a_single_job_on_the_session_plan(self):
        self._use_config()
        submit_mocks, _ = self._patch_ops(apply=_ok(stdout="apply output"))

        dto = await self.terraform.apply()

        self.assertTrue(dto.ok)
        self.assertEqual(dto.feedback, "")
        self.assertEqual(dto.stdout, "apply output")
        submit_mocks["init"].assert_not_awaited()
        submit_mocks["validate"].assert_not_awaited()
        submit_mocks["plan"].assert_not_awaited()
        submit_mocks["show"].assert_not_awaited()
        # No plan means no fingerprint to sample.
        self.git.get_workspace_revision.assert_not_awaited()

        apply_body = submit_mocks["apply"].await_args.kwargs["body"]
        self.assertEqual(apply_body.workspace_path, "/workspaces/demo")
        self.assertEqual(apply_body.plan_file, SESSION_PLAN_FILENAME)
        self.assertRegex(apply_body.plan_file, r"^[A-Za-z0-9._-]{1,128}$")

    async def test_apply_command_failure_maps_to_ok_false(self):
        self._use_config()
        self._patch_ops(
            apply=_failed_cmd("Error: stale plan", stdout="partial apply"),
        )

        dto = await self.terraform.apply()

        self.assertFalse(dto.ok)
        self.assertEqual(dto.feedback, "Error: stale plan")
        self.assertEqual(dto.stdout, "partial apply")

    async def test_apply_failed_job_raises_502_with_problem_detail(self):
        self._use_config()
        error = Problem(
            title="Internal Server Error", status=500, detail="state lock held"
        )
        self._patch_ops(
            apply=_job(JobStatus.FAILED, kind=JobKind.APPLY, error=error),
        )

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.terraform.apply()
        self.assertEqual(ctx.exception.error_code, 502)
        self.assertIn("state lock held", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
