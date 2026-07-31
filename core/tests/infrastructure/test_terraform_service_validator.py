# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for TerraformServiceValidator (async job submit → poll).

The generated client ops are mocked, so no IaC service is needed:
these cover the submit/poll orchestration and the mapping of the two
failure planes — a succeeded job's ValidateResult maps to the DTO
(false flags included), while failed/lost/rejected jobs raise
ExceptionHandler with the equivalent HTTP code.
"""

import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.clients.iac.models.import_result import ImportResult
from src.clients.iac.models.job import Job
from src.clients.iac.models.job_accepted import JobAccepted
from src.clients.iac.models.job_kind import JobKind
from src.clients.iac.models.job_status import JobStatus
from src.clients.iac.models.problem import Problem
from src.clients.iac.models.validate_result import ValidateResult
from src.domains.services.tracer_service import TracerService
from src.infrastructure.validators import terraform_service_validator as tsv
from src.shared.config.system_config import IacServiceConfig
from src.shared.exceptions import ExceptionHandler


def _job(status: JobStatus, result=None, error=None) -> Job:
    now = datetime.now(timezone.utc)
    return Job(
        job_id=uuid.uuid4(),
        kind=JobKind.VALIDATE,
        status=status,
        created_at=now,
        started_at=None if status is JobStatus.QUEUED else now,
        finished_at=now if status in (JobStatus.SUCCEEDED, JobStatus.FAILED) else None,
        result=result,
        error=error,
    )


class TestTerraformServiceValidator(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tracer_patcher = patch.object(
            TracerService, "get_current_tracer", return_value=MagicMock()
        )
        tracer_patcher.start()
        self.addCleanup(tracer_patcher.stop)

        self.session_svc = AsyncMock()
        self.validator = tsv.TerraformServiceValidator(
            workspace_path=Path("/workspaces/demo"),
            session_service=self.session_svc,
        )

    def _use_config(self, **overrides) -> IacServiceConfig:
        cfg = IacServiceConfig(
            enabled=True,
            endpoint="http://iac.test:8082",
            token_env="",
            timeout=1.0,
            job_poll_interval=0.0,
            **overrides,
        )
        patcher = patch.object(
            tsv,
            "system_config",
            SimpleNamespace(services=SimpleNamespace(iac=cfg)),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return cfg

    def _patch_ops(self, submit, polls=None) -> tuple[AsyncMock, AsyncMock]:
        submit_mock = AsyncMock(return_value=submit)
        if isinstance(polls, list):
            poll_mock = AsyncMock(side_effect=polls)
        else:
            poll_mock = AsyncMock(return_value=polls)
        for target, mock in (
            (tsv.validate_op, submit_mock),
            (tsv.get_job_op, poll_mock),
        ):
            patcher = patch.object(target, "asyncio", mock)
            patcher.start()
            self.addCleanup(patcher.stop)
        return submit_mock, poll_mock

    async def test_succeeded_job_result_maps_to_dto(self):
        self._use_config()
        accepted = JobAccepted(job_id=uuid.uuid4(), status=JobStatus.QUEUED)
        result = ValidateResult(
            validation=False,
            feedback="drift detected",
            terraform_plan="plan output",
            terraform_targets=["module.db"],
        )
        submit_mock, poll_mock = self._patch_ops(
            submit=accepted,
            polls=[
                _job(JobStatus.QUEUED),
                _job(JobStatus.RUNNING),
                _job(JobStatus.SUCCEEDED, result=result),
            ],
        )

        dto = await self.validator.validate(
            branch="main", targets=["module.db"], get_drift=True
        )

        self.assertFalse(dto.validation)
        self.assertEqual(dto.feedback, "drift detected")
        self.assertEqual(dto.terraform_plan, "plan output")
        self.assertEqual(dto.terraform_targets, ["module.db"])
        self.session_svc.update_status.assert_awaited_once()

        body = submit_mock.await_args.kwargs["body"]
        self.assertEqual(body.workspace_path, "/workspaces/demo")
        self.assertEqual(body.targets, ["module.db"])
        self.assertTrue(body.get_drift)
        self.assertEqual(poll_mock.await_args.kwargs["job_id"], accepted.job_id)

    async def test_failed_job_raises_502_with_problem_detail(self):
        self._use_config()
        error = Problem(
            title="Internal Server Error", status=500, detail="Key Vault unreachable"
        )
        self._patch_ops(
            submit=JobAccepted(job_id=uuid.uuid4(), status=JobStatus.QUEUED),
            polls=_job(JobStatus.FAILED, error=error),
        )

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.validator.validate(branch="main", targets=[])
        self.assertEqual(ctx.exception.error_code, 502)
        self.assertIn("Key Vault unreachable", ctx.exception.message)

    async def test_job_budget_exhausted_raises_504(self):
        self._use_config(job_timeout=0.0)
        self._patch_ops(
            submit=JobAccepted(job_id=uuid.uuid4(), status=JobStatus.QUEUED),
            polls=_job(JobStatus.RUNNING),
        )

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.validator.validate(branch="main", targets=[])
        self.assertEqual(ctx.exception.error_code, 504)

    async def test_submit_rejection_raises_502(self):
        for rejected in (
            Problem(title="Service Unavailable", status=503),
            None,
        ):
            with self.subTest(rejected=rejected):
                self._use_config()
                self._patch_ops(submit=rejected)

                with self.assertRaises(ExceptionHandler) as ctx:
                    await self.validator.validate(branch="main", targets=[])
                self.assertEqual(ctx.exception.error_code, 502)

    async def test_poll_problem_raises_502(self):
        self._use_config()
        self._patch_ops(
            submit=JobAccepted(job_id=uuid.uuid4(), status=JobStatus.QUEUED),
            polls=Problem(title="Not Found", status=404, detail="Unknown job"),
        )

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.validator.validate(branch="main", targets=[])
        self.assertEqual(ctx.exception.error_code, 502)
        self.assertIn("lost or rejected", ctx.exception.message)

    async def test_wrong_result_variant_raises_502(self):
        self._use_config()
        self._patch_ops(
            submit=JobAccepted(job_id=uuid.uuid4(), status=JobStatus.QUEUED),
            polls=_job(
                JobStatus.SUCCEEDED,
                result=ImportResult(success=True, feedback=""),
            ),
        )

        with self.assertRaises(ExceptionHandler) as ctx:
            await self.validator.validate(branch="main", targets=[])
        self.assertEqual(ctx.exception.error_code, 502)


if __name__ == "__main__":
    unittest.main()
