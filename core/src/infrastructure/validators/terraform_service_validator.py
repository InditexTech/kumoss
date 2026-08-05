# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""ITerraformValidator implementation that delegates to the IaC service.

This is the OSS-default validator. It calls the IaC microservice
(contracts/openapi/iac.v1.yaml) over HTTP using the generated client:
the POST enqueues a validation job and returns a job id immediately,
then the core polls ``GET /v1/jobs/{job_id}`` until the job is
terminal. Terraform-level failures surface inside the job's
``ValidateResult`` (false flag + feedback); service-level faults end
the job ``failed`` and are raised here as ExceptionHandler errors.
The service operates on a workspace path that must be visible to it;
the docker-compose setup mounts a shared volume into both the core and
the IaC service so that paths line up.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import override
from uuid import UUID

import httpx

from src.clients.iac.api.jobs import get_job as get_job_op
from src.clients.iac.api.validate import validate as validate_op
from src.clients.iac.client import AuthenticatedClient
from src.clients.iac.models.job import Job
from src.clients.iac.models.job_accepted import JobAccepted
from src.clients.iac.models.job_status import JobStatus
from src.clients.iac.models.problem import Problem
from src.clients.iac.models.validate_request import ValidateRequest
from src.clients.iac.models.validate_result import ValidateResult
from src.clients.iac.types import UNSET
from src.domains.dto import TerraformValidationDTO
from src.domains.interfaces.terraform_validator_interface import ITerraformValidator
from src.domains.services.session_service import SessionService
from src.domains.services.tracer_service import trace_terraform
from src.shared.config import system_config
from src.shared.config.system_config import IacServiceConfig
from src.shared.constants import SessionStatus
from src.shared.logger import logging
from src.shared.exceptions import ExceptionHandler


class TerraformServiceValidator(ITerraformValidator):
    """Validate by calling the IaC microservice."""

    def __init__(
        self,
        workspace_path: Path,
        session_service: SessionService,
    ):
        self.__workspace_path = workspace_path
        self.__session_svc = session_service

    @trace_terraform
    @override
    async def validate(
        self,
        branch: str,
        targets: list[str],
        get_drift: bool = False,
    ) -> TerraformValidationDTO:
        _ = await self.__session_svc.update_status(
            msg="Waiting for infrastructure as code to be validated.",
            status=SessionStatus.VALIDATING,
        )

        cfg = system_config.services.iac
        if not cfg.enabled or not cfg.endpoint:
            raise ExceptionHandler(
                message="IaC service is disabled or has no endpoint; cannot validate. "
                + "Enable services.iac in the system config.",
                error_code=500,
            )

        client = AuthenticatedClient(
            base_url=cfg.endpoint,
            token=cfg.token,
            timeout=httpx.Timeout(cfg.timeout),
        )
        body = ValidateRequest(
            workspace_path=str(self.__workspace_path),
            branch=branch if branch else UNSET,
            targets=targets,
            get_drift=get_drift,
        )
        try:
            async with client as c:
                accepted = await validate_op.asyncio(client=c, body=body)
                if not isinstance(accepted, JobAccepted):
                    raise ExceptionHandler(
                        f"IaC service did not accept the validation job: {accepted!r}",
                        502,
                    )
                job = await self.__poll_job(c, accepted.job_id, cfg)
        except httpx.TimeoutException as e:
            raise ExceptionHandler(f"IaC service timed out: {e}", 504) from e
        except httpx.RequestError as e:
            raise ExceptionHandler(f"IaC service unreachable: {e}", 502) from e

        if job.status is JobStatus.FAILED:
            raise ExceptionHandler(
                "IaC validation job failed on the service: "
                + self.__problem_text(job.error),
                502,
            )

        result = job.result
        if not isinstance(result, ValidateResult):
            raise ExceptionHandler(
                f"IaC service returned an unexpected job result: {result!r}", 502
            )
        if result.validation and result.feedback:
            logging.warning(result.feedback)
        return TerraformValidationDTO(
            validation=result.validation,
            feedback=result.feedback,
            terraform_plan=result.terraform_plan,
            terraform_targets=list(result.terraform_targets),
        )

    async def __poll_job(
        self,
        client: AuthenticatedClient,
        job_id: UUID,
        cfg: IacServiceConfig,
    ) -> Job:
        """Poll GET /v1/jobs/{job_id} until the job is terminal.

        ``cfg.job_timeout`` bounds the total wait (queue + pipeline); a
        non-``Job`` poll response means the job is gone (404 after a
        service restart or retention expiry) or unparseable — either
        way it will never finish, so fail immediately.
        """
        deadline = time.monotonic() + cfg.job_timeout
        while True:
            job = await get_job_op.asyncio(job_id=job_id, client=client)
            if not isinstance(job, Job):
                raise ExceptionHandler(
                    f"IaC service lost or rejected validation job {job_id}: {job!r}",
                    502,
                )
            if job.status in (JobStatus.SUCCEEDED, JobStatus.FAILED):
                return job
            if time.monotonic() >= deadline:
                raise ExceptionHandler(
                    f"IaC validation job {job_id} did not finish within "
                    + f"{cfg.job_timeout:.0f}s (last status: {job.status}).",
                    504,
                )
            await asyncio.sleep(cfg.job_poll_interval)

    @staticmethod
    def __problem_text(error: Problem | None) -> str:
        if not isinstance(error, Problem):
            return repr(error)
        if error.detail and error.detail is not UNSET:
            return f"{error.title}: {error.detail}"
        return error.title
