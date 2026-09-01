# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Terraform (raw-op orchestration).

The generated client op modules are mocked, so no IaC service is
needed: these cover the init → validate → plan (→ show) validation
sequencing and the init → plan → apply sequencing, the validation
boolean and drift parsing now owned by the core, and the mapping of
the two failure planes — a succeeded job with a non-zero exit_code
maps to a DTO with validation=False, while failed/lost/rejected jobs
raise ExceptionHandler with the equivalent HTTP code.
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
from src.domains.services.tracer_service import TracerService
from src.infrastructure.terraform import terraform as tv
from src.shared.config.system_config import IacServiceConfig
from src.shared.exceptions import ExceptionHandler


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


def _ok(stdout: str = "", stderr: str = "") -> OperationResult:
    return OperationResult(exit_code=0, stdout=stdout, stderr=stderr)


def _failed_cmd(stderr: str, stdout: str = "") -> OperationResult:
    return OperationResult(exit_code=1, stdout=stdout, stderr=stderr)


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
    """Shared fixtures: tracer/session mocks, config patch, op patching."""

    def setUp(self):
        tracer_patcher = patch.object(
            TracerService, "get_current_tracer", return_value=MagicMock()
        )
        tracer_patcher.start()
        self.addCleanup(tracer_patcher.stop)

        self.terraform = tv.Terraform(
            workspace_path=Path("/workspaces/demo"),
        )

    def _use_config(self, **overrides) -> IacServiceConfig:
        defaults = dict(
            enabled=True,
            endpoint="http://iac.test:8082",
            token_env="",
            timeout=1.0,
            job_poll_interval=0.0,
        )
        defaults.update(overrides)
        cfg = IacServiceConfig(**defaults)
        patcher = patch.object(
            tv,
            "system_config",
            SimpleNamespace(services=SimpleNamespace(iac=cfg)),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return cfg

    def _patch_ops(self, **outcomes) -> tuple[dict[str, AsyncMock], AsyncMock]:
        """Patch the five op modules and the job poll.

        ``outcomes`` maps op name (init/validate/plan/show/apply) to
        either an OperationResult (the op's job succeeds with it), a
        Job (the poll returns it verbatim), or a non-JobAccepted submit
        response (Problem / None). Ops without an outcome fail the test
        if submitted.
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
                outcome = outcomes[name]
                if isinstance(outcome, OperationResult):
                    outcome = _job(
                        JobStatus.SUCCEEDED, kind=JobKind(name), result=outcome
                    )
                if isinstance(outcome, Job):
                    job_id = uuid.uuid4()
                    jobs_by_id[job_id] = outcome
                    accepted = JobAccepted(job_id=job_id, status=JobStatus.QUEUED)
                    mock = AsyncMock(return_value=accepted)
                else:
                    # Rejected submission: Problem / None straight back.
                    mock = AsyncMock(return_value=outcome)
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


class TestTerraformValidate(_TerraformTestCase):
    async def test_all_ops_succeed_without_drift(self):
        self._use_config()
        submit_mocks, _ = self._patch_ops(
            init=_ok(),
            validate=_ok(),
            plan=_ok(stdout="plan output"),
            show=_ok(stdout=NO_CHANGES_PLAN_JSON),
        )

        dto = await self.terraform.validate(
            branch="main", targets=["module.db"], get_drift=True
        )

        self.assertTrue(dto.validation)
        self.assertEqual(dto.feedback, "")
        self.assertEqual(dto.terraform_plan, "plan output")
        self.assertEqual(dto.terraform_targets, ["module.db"])

        init_body = submit_mocks["init"].await_args.kwargs["body"]
        self.assertEqual(init_body.workspace_path, "/workspaces/demo")
        plan_body = submit_mocks["plan"].await_args.kwargs["body"]
        self.assertEqual(plan_body.targets, ["module.db"])

    async def test_drift_found_maps_to_validation_false(self):
        self._use_config()
        self._patch_ops(
            init=_ok(),
            validate=_ok(),
            plan=_ok(stdout="plan output"),
            show=_ok(stdout=DRIFTED_PLAN_JSON),
        )

        dto = await self.terraform.validate(branch="main", targets=[], get_drift=True)

        self.assertFalse(dto.validation)
        self.assertEqual(dto.terraform_plan, "plan output")
        drift = json.loads(dto.feedback)
        self.assertEqual(len(drift), 1)
        self.assertEqual(drift[0]["address"], "azurerm_resource_group.main")
        self.assertEqual(drift[0]["action"], "update resource")
        # reversed=True swaps old/new so the summary reads as "what to
        # change to get back in sync" rather than what the plan would do.
        self.assertEqual(
            drift[0]["changes"]["values_changed"]["root['tags']['env']"],
            {"old_value": "dev", "new_value": "prod"},
        )

    async def test_without_get_drift_show_is_skipped(self):
        self._use_config()
        submit_mocks, _ = self._patch_ops(
            init=_ok(),
            validate=_ok(),
            plan=_ok(stdout="plan output"),
        )

        dto = await self.terraform.validate(branch="main", targets=[], get_drift=False)

        self.assertTrue(dto.validation)
        self.assertEqual(dto.feedback, "")
        self.assertEqual(dto.terraform_plan, "plan output")
        submit_mocks["show"].assert_not_awaited()

    async def test_init_failure_returns_dto_with_stderr(self):
        self._use_config()
        self._patch_ops(init=_failed_cmd("Error: backend init failed"))

        dto = await self.terraform.validate(branch="main", targets=["module.db"])

        self.assertFalse(dto.validation)
        self.assertEqual(dto.feedback, "Error: backend init failed")
        self.assertEqual(dto.terraform_plan, "")
        self.assertEqual(dto.terraform_targets, ["module.db"])

    async def test_plan_failure_returns_stdout_as_plan(self):
        self._use_config()
        self._patch_ops(
            init=_ok(),
            validate=_ok(),
            plan=_failed_cmd("Error: auth", stdout="partial plan"),
        )

        dto = await self.terraform.validate(branch="main", targets=[], get_drift=True)

        self.assertFalse(dto.validation)
        self.assertEqual(dto.feedback, "Error: auth")
        self.assertEqual(dto.terraform_plan, "partial plan")

    async def test_plan_and_show_receive_same_plan_file(self):
        self._use_config()
        submit_mocks, _ = self._patch_ops(
            init=_ok(),
            validate=_ok(),
            plan=_ok(),
            show=_ok(stdout=NO_CHANGES_PLAN_JSON),
        )

        _ = await self.terraform.validate(branch="main", targets=[], get_drift=True)

        plan_file = submit_mocks["plan"].await_args.kwargs["body"].plan_file
        show_file = submit_mocks["show"].await_args.kwargs["body"].plan_file
        self.assertEqual(plan_file, show_file)
        self.assertRegex(plan_file, r"^[A-Za-z0-9._-]{1,128}$")

    async def test_failed_job_raises_502_with_problem_detail(self):
        self._use_config()
        error = Problem(
            title="Internal Server Error", status=500, detail="Key Vault unreachable"
        )
        self._patch_ops(
            init=_job(JobStatus.FAILED, kind=JobKind.INIT, error=error),
        )

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.terraform.validate(branch="main", targets=[])
        self.assertEqual(ctx.exception.error_code, 502)
        self.assertIn("Key Vault unreachable", ctx.exception.message)

    async def test_job_budget_exhausted_raises_504(self):
        self._use_config(job_timeout=0.0)
        self._patch_ops(init=_job(JobStatus.RUNNING, kind=JobKind.INIT))

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.terraform.validate(branch="main", targets=[])
        self.assertEqual(ctx.exception.error_code, 504)

    async def test_submit_rejection_raises_502(self):
        for rejected in (
            Problem(title="Service Unavailable", status=503),
            None,
        ):
            with self.subTest(rejected=rejected):
                self._use_config()
                self._patch_ops(init=rejected)

                with self.assertRaises(ExceptionHandler) as ctx:
                    await self.terraform.validate(branch="main", targets=[])
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
            await self.terraform.validate(branch="main", targets=[])
        self.assertEqual(ctx.exception.error_code, 502)
        self.assertIn("lost or rejected", ctx.exception.message)

    async def test_missing_result_on_succeeded_job_raises_502(self):
        self._use_config()
        self._patch_ops(
            init=_job(JobStatus.SUCCEEDED, kind=JobKind.INIT, result=None),
        )

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.terraform.validate(branch="main", targets=[])
        self.assertEqual(ctx.exception.error_code, 502)

    async def test_unparseable_show_json_raises_502(self):
        self._use_config()
        self._patch_ops(
            init=_ok(),
            validate=_ok(),
            plan=_ok(),
            show=_ok(stdout="not json"),
        )

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.terraform.validate(branch="main", targets=[], get_drift=True)
        self.assertEqual(ctx.exception.error_code, 502)


class _ImportTestCase(_TerraformTestCase):
    """Extends _TerraformTestCase with import op patching."""

    def _patch_import_ops(self, **outcomes) -> tuple[dict[str, AsyncMock], AsyncMock]:
        """Patch init + import op modules and the job poll.

        ``outcomes`` maps op name (init/state/scope/import) to either an
        OperationResult, a Job, or a non-JobAccepted response.
        """
        jobs_by_id: dict[uuid.UUID, Job] = {}
        submit_mocks: dict[str, AsyncMock] = {}
        kind_map = {
            "init": (tv.init_op, JobKind.INIT),
            "state": (tv.state_op, JobKind.STATE_RESOURCE_IDS),
            "scope": (tv.scope_op, JobKind.SCOPE_RESOURCE_IDS),
            "import": (tv.import_op, JobKind.IMPORT),
        }
        for name, (module, kind) in kind_map.items():
            if name not in outcomes:
                mock = AsyncMock(
                    side_effect=AssertionError(f"{name} op should not be submitted")
                )
            else:
                outcome = outcomes[name]
                if isinstance(outcome, OperationResult):
                    outcome = _job(JobStatus.SUCCEEDED, kind=kind, result=outcome)
                if isinstance(outcome, Job):
                    job_id = uuid.uuid4()
                    jobs_by_id[job_id] = outcome
                    accepted = JobAccepted(job_id=job_id, status=JobStatus.QUEUED)
                    mock = AsyncMock(return_value=accepted)
                else:
                    mock = AsyncMock(return_value=outcome)
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


class TestTerraformStateResourceIds(_ImportTestCase):
    async def test_returns_parsed_resource_ids(self):
        self._use_config()
        self._patch_import_ops(
            init=_ok(),
            state=_ok(
                stdout=json.dumps(["azurerm_resource_group.main", "azurerm_vnet.v1"])
            ),
        )

        ids = await self.terraform.state_resource_ids()

        self.assertEqual(ids, ["azurerm_resource_group.main", "azurerm_vnet.v1"])

    async def test_init_failure_raises(self):
        self._use_config()
        self._patch_import_ops(init=_failed_cmd("Error: backend init failed"))

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.terraform.state_resource_ids()
        self.assertEqual(ctx.exception.error_code, 502)
        self.assertIn("init failed", ctx.exception.message)

    async def test_state_op_failure_raises(self):
        self._use_config()
        self._patch_import_ops(
            init=_ok(),
            state=_failed_cmd("Error: state pull failed"),
        )

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.terraform.state_resource_ids()
        self.assertEqual(ctx.exception.error_code, 502)
        self.assertIn("state pull failed", ctx.exception.message)

    async def test_disabled_config_raises(self):
        self._use_config(enabled=False)
        self._patch_import_ops()

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.terraform.state_resource_ids()
        self.assertEqual(ctx.exception.error_code, 500)


class TestTerraformScopeResourceIds(_ImportTestCase):
    async def test_returns_parsed_scope_ids(self):
        self._use_config()
        submit_mocks, _ = self._patch_import_ops(
            init=_ok(),
            scope=_ok(stdout=json.dumps(["res-1", "res-2", "res-3"])),
        )

        ids = await self.terraform.scope_resource_ids(
            scope_id="scope-123",
            terraform_provider="azure",
        )

        self.assertEqual(ids, ["res-1", "res-2", "res-3"])
        scope_body = submit_mocks["scope"].await_args.kwargs["body"]
        self.assertEqual(scope_body.scope_id, "scope-123")
        self.assertEqual(scope_body.terraform_provider, "azure")

    async def test_init_failure_raises(self):
        self._use_config()
        self._patch_import_ops(init=_failed_cmd("Error: backend init failed"))

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.terraform.scope_resource_ids(
                scope_id="scope-123",
                terraform_provider="azure",
            )
        self.assertEqual(ctx.exception.error_code, 502)

    async def test_scope_op_failure_raises(self):
        self._use_config()
        self._patch_import_ops(
            init=_ok(),
            scope=_failed_cmd("Error: scope retrieval failed"),
        )

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.terraform.scope_resource_ids(
                scope_id="scope-123",
                terraform_provider="azure",
            )
        self.assertEqual(ctx.exception.error_code, 502)
        self.assertIn("scope resource IDs failed", ctx.exception.message)

    async def test_disabled_config_raises(self):
        self._use_config(enabled=False)
        self._patch_import_ops()

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.terraform.scope_resource_ids(
                scope_id="scope-123",
                terraform_provider="azure",
            )
        self.assertEqual(ctx.exception.error_code, 500)


class TestTerraformImportResource(_ImportTestCase):
    async def test_import_success(self):
        self._use_config()
        submit_mocks, _ = self._patch_import_ops(
            init=_ok(),
            **{"import": _ok(stdout="import output")},
        )

        dto = await self.terraform.import_resource(
            address="azurerm_resource_group.main",
            resource_id="/subscriptions/.../rg/main",
        )

        self.assertTrue(dto.validation)
        self.assertEqual(dto.feedback, "")
        self.assertEqual(dto.terraform_plan, "import output")
        self.assertEqual(dto.terraform_targets, ["azurerm_resource_group.main"])
        import_body = submit_mocks["import"].await_args.kwargs["body"]
        self.assertEqual(import_body.address, "azurerm_resource_group.main")
        self.assertEqual(import_body.resource_id, "/subscriptions/.../rg/main")

    async def test_import_failure_returns_dto_with_validation_false(self):
        self._use_config()
        self._patch_import_ops(
            init=_ok(),
            **{"import": _failed_cmd("Error: cannot import", stdout="partial output")},
        )

        dto = await self.terraform.import_resource(
            address="azurerm_resource_group.main",
            resource_id="/subscriptions/.../rg/main",
        )

        self.assertFalse(dto.validation)
        self.assertEqual(dto.feedback, "Error: cannot import")
        self.assertEqual(dto.terraform_plan, "partial output")
        self.assertEqual(dto.terraform_targets, ["azurerm_resource_group.main"])

    async def test_init_failure_raises(self):
        self._use_config()
        self._patch_import_ops(init=_failed_cmd("Error: backend init failed"))

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.terraform.import_resource(
                address="azurerm_resource_group.main",
                resource_id="res-1",
            )
        self.assertEqual(ctx.exception.error_code, 502)

    async def test_disabled_config_raises(self):
        self._use_config(enabled=False)
        self._patch_import_ops()

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.terraform.import_resource(
                address="azurerm_resource_group.main",
                resource_id="res-1",
            )
        self.assertEqual(ctx.exception.error_code, 500)

    async def test_failed_job_raises_502(self):
        self._use_config()
        error = Problem(
            title="Internal Server Error", status=500, detail="state lock held"
        )
        self._patch_import_ops(
            init=_ok(),
            **{"import": _job(JobStatus.FAILED, kind=JobKind.IMPORT, error=error)},
        )

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.terraform.import_resource(
                address="azurerm_resource_group.main",
                resource_id="res-1",
            )
        self.assertEqual(ctx.exception.error_code, 502)
        self.assertIn("state lock held", ctx.exception.message)


class TestTerraformApply(_TerraformTestCase):
    async def test_apply_success(self):
        self._use_config()
        submit_mocks, _ = self._patch_ops(
            init=_ok(),
            plan=_ok(stdout="plan output"),
            apply=_ok(stdout="apply output"),
        )

        dto = await self.terraform.apply(targets=["module.foo"])

        self.assertTrue(dto.validation)
        self.assertEqual(dto.feedback, "")
        self.assertEqual(dto.terraform_plan, "apply output")
        self.assertEqual(dto.terraform_targets, ["module.foo"])
        submit_mocks["validate"].assert_not_awaited()
        submit_mocks["show"].assert_not_awaited()

        plan_body = submit_mocks["plan"].await_args.kwargs["body"]
        self.assertEqual(plan_body.targets, ["module.foo"])
        apply_body = submit_mocks["apply"].await_args.kwargs["body"]
        self.assertEqual(apply_body.workspace_path, "/workspaces/demo")
        self.assertEqual(apply_body.plan_file, plan_body.plan_file)

    async def test_apply_init_failure_returns_dto_with_stderr(self):
        self._use_config()
        self._patch_ops(init=_failed_cmd("Error: backend init failed"))

        dto = await self.terraform.apply(targets=["module.foo"])

        self.assertFalse(dto.validation)
        self.assertEqual(dto.feedback, "Error: backend init failed")
        self.assertEqual(dto.terraform_plan, "")
        self.assertEqual(dto.terraform_targets, ["module.foo"])

    async def test_apply_plan_failure_returns_stdout_as_plan(self):
        self._use_config()
        self._patch_ops(
            init=_ok(),
            plan=_failed_cmd("Error: auth", stdout="partial plan"),
        )

        dto = await self.terraform.apply(targets=[])

        self.assertFalse(dto.validation)
        self.assertEqual(dto.feedback, "Error: auth")
        self.assertEqual(dto.terraform_plan, "partial plan")

    async def test_apply_command_failure_maps_to_validation_false(self):
        self._use_config()
        self._patch_ops(
            init=_ok(),
            plan=_ok(stdout="plan output"),
            apply=_failed_cmd("Error: apply", stdout="partial apply"),
        )

        dto = await self.terraform.apply(targets=[])

        self.assertFalse(dto.validation)
        self.assertEqual(dto.feedback, "Error: apply")
        self.assertEqual(dto.terraform_plan, "partial apply")

    async def test_apply_failed_job_raises_502_with_problem_detail(self):
        self._use_config()
        error = Problem(
            title="Internal Server Error", status=500, detail="state lock held"
        )
        self._patch_ops(
            init=_ok(),
            plan=_ok(),
            apply=_job(JobStatus.FAILED, kind=JobKind.APPLY, error=error),
        )

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.terraform.apply(targets=[])
        self.assertEqual(ctx.exception.error_code, 502)
        self.assertIn("state lock held", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
