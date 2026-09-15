# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""ITerraform implementation that delegates to the IaC service.

This is the OSS-default terraform service. The IaC microservice
(contracts/openapi/iac.v1.yaml) is a raw terraform executor: each POST
enqueues a job running exactly one terraform command and the job's
result is the command's raw ``{exit_code, stdout, stderr}``. All
orchestration lives here: this class sequences ``init`` → ``validate``
→ ``plan`` (→ ``show`` under ``get_drift``) for validation — with
``init`` cached per instance, so the retry loops that call ``validate``
repeatedly on the same workspace initialize it only once — decides the
validation boolean, and parses the plan JSON into the drift summary.
An apply is a single ``apply`` job executing the plan artifact already
present in the workspace (the session's pinned workspace, promoted at
the end of the round that produced the plan); no init or plan runs at
apply time. Each operation is submitted with the generated client and
polled at ``GET /v1/jobs/{job_id}`` until terminal; a non-zero
``exit_code`` is a terraform-level failure reported through the
returned DTO, while a ``failed`` job is a service-level fault raised as
an ExceptionHandler error. Every operation runs on whatever is on disk
at the workspace path, which must be visible to the service. ``init``,
``plan`` and ``apply`` reach a cloud API, so they carry the session's
``scope_id`` (subscription / project / account) together with its
``terraform_provider``: generated provider blocks do not name a scope,
so the service injects it into the engine's environment for those three
commands where the provider has a variable that names a scope (Azure
and GCP). ``validate`` and ``show`` reach no cloud API and are
submitted unscoped.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import ModuleType
from typing import override
from uuid import UUID

import httpx

from .utils import TerraformUtils
from src.clients.iac.api.apply import apply as apply_op
from src.clients.iac.api.init import init as init_op
from src.clients.iac.api.jobs import get_job as get_job_op
from src.clients.iac.api.plan import plan as plan_op
from src.clients.iac.api.show import show as show_op
from src.clients.iac.api.validate import validate as validate_op
from src.clients.iac.client import AuthenticatedClient
from src.clients.iac.models.apply_request import ApplyRequest
from src.clients.iac.models.init_request import InitRequest
from src.clients.iac.models.job import Job
from src.clients.iac.models.job_accepted import JobAccepted
from src.clients.iac.models.job_status import JobStatus
from src.clients.iac.models.operation_result import OperationResult
from src.clients.iac.models.plan_request import PlanRequest
from src.clients.iac.models.problem import Problem
from src.clients.iac.models.show_request import ShowRequest
from src.clients.iac.models.terraform_provider import (
    TerraformProvider as IacTerraformProvider,
)
from src.clients.iac.models.validate_request import ValidateRequest
from src.clients.iac.types import UNSET
from src.domains.dto import TerraformValidationDTO
from src.domains.interfaces.terraform_interface import ITerraform
from src.domains.services.tracer_service import trace_terraform
from src.shared.config import system_config
from src.shared.config.system_config import IacServiceConfig
from src.shared.constants import TerraformProvider
from src.shared.exceptions import ExceptionHandler


OperationRequest = (
    InitRequest | ValidateRequest | PlanRequest | ShowRequest | ApplyRequest
)


class Terraform(ITerraform):
    """Validate and apply by orchestrating raw terraform jobs on the IaC service."""

    def __init__(
        self,
        workspace_path: Path,
        scope_id: str,
        terraform_provider: TerraformProvider,
    ):
        self.__workspace_path = workspace_path
        self.__scope_id = scope_id
        self.__terraform_provider = IacTerraformProvider(terraform_provider.value)
        self.__initialized = False

    @trace_terraform
    @override
    async def validate(
        self,
        targets: list[str],
        get_drift: bool,
    ) -> TerraformValidationDTO:
        cfg = system_config.services.iac
        client = AuthenticatedClient(
            base_url=cfg.endpoint,
            token=cfg.token,
            timeout=httpx.Timeout(cfg.timeout),
        )
        try:
            async with client as c:
                init_res = await self.__ensure_init(c, cfg)
                if init_res is not None:
                    return TerraformValidationDTO(
                        validation=False,
                        feedback=init_res.stderr or "terraform init failed",
                        terraform_plan="",
                        terraform_targets=targets,
                    )

                validate_res = await self.__run_initialized_op(
                    c,
                    validate_op,
                    ValidateRequest(
                        workspace_path=self.__workspace_path.as_posix(),
                    ),
                    cfg,
                )
                if validate_res.exit_code != 0:
                    return TerraformValidationDTO(
                        validation=False,
                        feedback=validate_res.stderr or "terraform validate failed",
                        terraform_plan="",
                        terraform_targets=targets,
                    )

                plan_res = await self.__run_initialized_op(
                    c,
                    plan_op,
                    PlanRequest(
                        workspace_path=self.__workspace_path.as_posix(),
                        scope_id=self.__scope_id,
                        terraform_provider=self.__terraform_provider,
                        plan_file=system_config.paths.session_plan_filename,
                        targets=targets,
                    ),
                    cfg,
                )
                if plan_res.exit_code != 0:
                    return TerraformValidationDTO(
                        validation=False,
                        feedback=plan_res.stderr or "terraform plan failed",
                        terraform_plan=plan_res.stdout,
                        terraform_targets=targets,
                    )

                if not get_drift:
                    return TerraformValidationDTO(
                        validation=True,
                        feedback="",
                        terraform_plan=plan_res.stdout,
                        terraform_targets=targets,
                    )

                show_res = await self.__run_initialized_op(
                    c,
                    show_op,
                    ShowRequest(
                        workspace_path=self.__workspace_path.as_posix(),
                        plan_file=system_config.paths.session_plan_filename,
                    ),
                    cfg,
                )
        except httpx.TimeoutException as e:
            raise ExceptionHandler(f"IaC service timed out: {e}", 504) from e
        except httpx.RequestError as e:
            raise ExceptionHandler(f"IaC service unreachable: {e}", 502) from e

        if show_res.exit_code != 0:
            return TerraformValidationDTO(
                validation=False,
                feedback=show_res.stderr or "terraform show failed",
                terraform_plan=plan_res.stdout,
                terraform_targets=targets,
            )

        try:
            plan_json = json.loads(show_res.stdout)
        except json.JSONDecodeError as e:
            raise ExceptionHandler(
                f"terraform show succeeded but returned unparseable JSON: {e}", 502
            ) from e

        drift = TerraformUtils.plan_to_drift(plan_json=plan_json, reversed=True)
        return TerraformValidationDTO(
            validation=not drift,
            feedback=json.dumps(drift) if drift else "",
            terraform_plan=plan_res.stdout,
            terraform_targets=targets,
        )

    @trace_terraform
    @override
    async def apply(self) -> TerraformValidationDTO:
        cfg = system_config.services.iac
        client = AuthenticatedClient(
            base_url=cfg.endpoint,
            token=cfg.token,
            timeout=httpx.Timeout(cfg.timeout),
        )
        try:
            async with client as c:
                apply_res = await self.__run_op(
                    c,
                    apply_op,
                    ApplyRequest(
                        workspace_path=str(self.__workspace_path),
                        scope_id=self.__scope_id,
                        terraform_provider=self.__terraform_provider,
                        plan_file=system_config.paths.session_plan_filename,
                    ),
                    cfg,
                )
        except httpx.TimeoutException as e:
            raise ExceptionHandler(f"IaC service timed out: {e}", 504) from e
        except httpx.RequestError as e:
            raise ExceptionHandler(f"IaC service unreachable: {e}", 502) from e

        if apply_res.exit_code != 0:
            return TerraformValidationDTO(
                validation=False,
                feedback=apply_res.stderr or "terraform apply failed",
                terraform_plan=apply_res.stdout,
                terraform_targets=[],
            )
        return TerraformValidationDTO(
            validation=True,
            feedback="",
            terraform_plan=apply_res.stdout,
            terraform_targets=[],
        )

    async def __ensure_init(
        self,
        client: AuthenticatedClient,
        cfg: IacServiceConfig,
    ) -> OperationResult | None:
        """Initialize the workspace unless this instance already did.

        Returns None once the workspace is initialized, or the failing
        OperationResult (the flag stays unset, so the next call tries
        again).
        """
        if self.__initialized:
            return None
        init_res = await self.__run_op(
            client,
            init_op,
            InitRequest(
                workspace_path=str(self.__workspace_path),
                scope_id=self.__scope_id,
                terraform_provider=self.__terraform_provider,
            ),
            cfg,
        )
        if init_res.exit_code != 0:
            return init_res
        self.__initialized = True
        return None

    async def __run_initialized_op(
        self,
        client: AuthenticatedClient,
        submit_module: ModuleType,
        body: OperationRequest,
        cfg: IacServiceConfig,
    ) -> OperationResult:
        """Run an op that needs an initialized workspace, re-initializing once.

        The cached init can go stale mid-request: the generation loop
        may add a provider or module block between iterations, after
        which terraform fails asking to run ``terraform init``. That
        failure clears the cache, re-runs init, and retries the op
        exactly once; any further failure is returned to the caller as
        a normal terraform failure.
        """
        res = await self.__run_op(client, submit_module, body, cfg)
        if res.exit_code == 0 or not self.__needs_init(res):
            return res
        self.__initialized = False
        init_res = await self.__ensure_init(client, cfg)
        if init_res is not None:
            return init_res
        return await self.__run_op(client, submit_module, body, cfg)

    @staticmethod
    def __needs_init(res: OperationResult) -> bool:
        return "terraform init" in f"{res.stderr}\n{res.stdout}".lower()

    async def __run_op(
        self,
        client: AuthenticatedClient,
        submit_module: ModuleType,
        body: OperationRequest,
        cfg: IacServiceConfig,
    ) -> OperationResult:
        """Submit one terraform operation and poll it to completion.

        Returns the raw OperationResult (the caller decides what a
        non-zero exit code means); anything else — a rejected
        submission, a ``failed`` job, or an unexpected result shape —
        is a service-level fault raised as an ExceptionHandler error.
        """
        op_name = submit_module.__name__.rsplit(".", 1)[-1]
        accepted = await submit_module.asyncio(client=client, body=body)
        if not isinstance(accepted, JobAccepted):
            raise ExceptionHandler(
                f"IaC service did not accept the {op_name} job: {accepted!r}", 502
            )
        job = await self.__poll_job(client, accepted.job_id, cfg)
        if job.status is JobStatus.FAILED:
            raise ExceptionHandler(
                f"IaC {op_name} job failed on the service: "
                + self.__problem_text(job.error),
                502,
            )
        result = job.result
        if not isinstance(result, OperationResult):
            raise ExceptionHandler(
                f"IaC service returned an unexpected job result: {result!r}", 502
            )
        return result

    async def __poll_job(
        self,
        client: AuthenticatedClient,
        job_id: UUID,
        cfg: IacServiceConfig,
    ) -> Job:
        """Poll GET /v1/jobs/{job_id} until the job is terminal.

        ``cfg.job_timeout`` bounds the total wait (queue + command); a
        non-``Job`` poll response means the job is gone (404 after a
        service restart or retention expiry) or unparseable — either
        way it will never finish, so fail immediately.
        """
        deadline = time.monotonic() + cfg.job_timeout
        while True:
            try:
                job = await get_job_op.asyncio(job_id=job_id, client=client)
            except httpx.RemoteProtocolError:
                job = await get_job_op.asyncio(job_id=job_id, client=client)
            if not isinstance(job, Job):
                raise ExceptionHandler(
                    f"IaC service lost or rejected job {job_id}: {job!r}",
                    502,
                )
            if job.status in (JobStatus.SUCCEEDED, JobStatus.FAILED):
                return job
            if time.monotonic() >= deadline:
                raise ExceptionHandler(
                    f"IaC job {job_id} did not finish within "
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
