# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""ITerraform implementation that delegates to the IaC service.

This is the OSS-default terraform service. The IaC microservice
(contracts/openapi/iac.v1.yaml) is a raw terraform executor: each POST
enqueues a job running exactly one terraform command and the job's
result is the command's raw ``{exit_code, stdout, stderr}``. All
orchestration lives here, as three verbs over the plan artifact.
``plan`` sequences ``init`` → ``validate`` → ``plan -out`` — with
``init`` cached per instance, so the retry loops that plan the same
workspace repeatedly initialize it only once — decides the validation
boolean, and hands back a PlanRef naming the artifact it wrote.
``drift`` runs ``show`` on such a ref and parses the plan JSON into the
drift summary, which is how a caller that already holds a plan reads
its drift without paying for a second one. The ref carries a
fingerprint of the workspace, sampled immediately after the plan job
returns (never before: ``plan -out`` writes the plan file and ``init``
populates the provider cache, so an earlier sample would never match);
a ref whose fingerprint has moved is re-planned before its drift is
read, and one naming another workspace is refused.
``apply`` is a single ``apply`` job executing the plan artifact already
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

Import discovery follows the same planes: a ``state pull`` that exits
non-zero leaves the managed set unknown, so it is raised, while a
failed cloud query in ``scope-resource-ids`` is a normal outcome of
that endpoint (unknown scope, credentials, a provider with no
inventory query) and comes back as an empty scope whose feedback is the
command's ``stderr`` — nothing to import, not a broken session.
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

from .backend import TerraformBackend
from .utils import TerraformUtils
from src.clients.iac.api.apply import apply as apply_op
from src.clients.iac.api.init import init as init_op
from src.clients.iac.api.jobs import get_job as get_job_op
from src.clients.iac.api.plan import plan as plan_op
from src.clients.iac.api.show import show as show_op
from src.clients.iac.api.validate import validate as validate_op
from src.clients.iac.api.import_ import state_resource_ids as state_op
from src.clients.iac.api.import_ import scope_resource_ids as scope_op
from src.clients.iac.api.import_ import import_resource as import_op
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
from src.clients.iac.models.state_resource_ids_request import StateResourceIdsRequest
from src.clients.iac.models.scope_resource_ids_request import ScopeResourceIdsRequest
from src.clients.iac.models.import_request import ImportRequest
from src.clients.iac.types import UNSET
from src.domains.dto import (
    TerraformApplyDTO,
    TerraformDiscoveryDTO,
    TerraformDriftDTO,
    TerraformImportResourceDTO,
    TerraformPlanDTO,
)
from src.domains.interfaces.git_interface import IGit
from src.domains.interfaces.terraform_interface import ITerraform
from src.domains.services.tracer_service import trace_terraform
from src.domains.value_objects import PlanRef
from src.shared.config import system_config
from src.shared.config.system_config import IacServiceConfig
from src.shared.constants import TerraformProvider
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging


OperationRequest = (
    InitRequest
    | ValidateRequest
    | PlanRequest
    | ShowRequest
    | ApplyRequest
    | StateResourceIdsRequest
    | ScopeResourceIdsRequest
    | ImportRequest
)


class Terraform(ITerraform):
    """Plan, read drift and apply by orchestrating raw terraform jobs on the IaC service."""

    def __init__(
        self,
        workspace_path: Path,
        git: IGit,
        scope_id: str,
        terraform_provider: TerraformProvider,
        backend: TerraformBackend,
    ):
        self.__workspace_path = workspace_path
        self.__git = git
        self.__scope_id = scope_id
        self.__terraform_provider = IacTerraformProvider(terraform_provider.value)
        self.__backend = backend
        self.__initialized = False

    @trace_terraform
    @override
    async def plan(self, targets: list[str]) -> TerraformPlanDTO:
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
                    return TerraformPlanDTO(
                        ok=False,
                        feedback=init_res.stderr or "terraform init failed",
                        stdout="",
                        targets=targets,
                        plan=None,
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
                    return TerraformPlanDTO(
                        ok=False,
                        feedback=validate_res.stderr or "terraform validate failed",
                        stdout="",
                        targets=targets,
                        plan=None,
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
        except httpx.TimeoutException as e:
            raise ExceptionHandler(f"IaC service timed out: {e}", 504) from e
        except httpx.RequestError as e:
            raise ExceptionHandler(f"IaC service unreachable: {e}", 502) from e

        if plan_res.exit_code != 0:
            return TerraformPlanDTO(
                ok=False,
                feedback=plan_res.stderr or "terraform plan failed",
                stdout=plan_res.stdout,
                targets=targets,
                plan=None,
            )

        return TerraformPlanDTO(
            ok=True,
            feedback="",
            stdout=plan_res.stdout,
            targets=targets,
            plan=PlanRef(
                workspace=self.__workspace_path,
                plan_file=system_config.paths.session_plan_filename,
                targets=tuple(targets),
                commit=await self.__git.get_workspace_revision(),
                stdout=plan_res.stdout,
            ),
        )

    @trace_terraform
    @override
    async def drift(self, plan: PlanRef) -> TerraformDriftDTO:
        if plan.workspace != self.__workspace_path:
            raise ExceptionHandler(
                f"Plan {plan} belongs to another workspace than "
                + f"{self.__workspace_path.as_posix()}",
                500,
            )

        if await self.__git.get_workspace_revision() != plan.commit:
            logging.warning(
                "Workspace changed since the plan; re-planning before reading drift"
            )
            plan_res = await self.plan(list(plan.targets))
            if plan_res.plan is None:
                return TerraformDriftDTO(
                    in_sync=False,
                    drift="",
                    feedback=plan_res.feedback,
                    stdout=plan_res.stdout,
                    plan=None,
                )
            plan = plan_res.plan

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
                    return TerraformDriftDTO(
                        in_sync=False,
                        drift="",
                        feedback=init_res.stderr or "terraform init failed",
                        stdout=plan.stdout,
                        plan=None,
                    )

                show_res = await self.__run_initialized_op(
                    c,
                    show_op,
                    ShowRequest(
                        workspace_path=plan.workspace.as_posix(),
                        plan_file=plan.plan_file,
                    ),
                    cfg,
                )
        except httpx.TimeoutException as e:
            raise ExceptionHandler(f"IaC service timed out: {e}", 504) from e
        except httpx.RequestError as e:
            raise ExceptionHandler(f"IaC service unreachable: {e}", 502) from e

        if show_res.exit_code != 0:
            return TerraformDriftDTO(
                in_sync=False,
                drift="",
                feedback=show_res.stderr or "terraform show failed",
                stdout=plan.stdout,
                plan=None,
            )

        try:
            plan_json = json.loads(show_res.stdout)
        except json.JSONDecodeError as e:
            raise ExceptionHandler(
                f"terraform show succeeded but returned unparseable JSON: {e}", 502
            ) from e

        drift = TerraformUtils.plan_to_drift(plan_json=plan_json, reversed=True)
        return TerraformDriftDTO(
            in_sync=not drift,
            drift=json.dumps(drift) if drift else "",
            feedback="",
            stdout=plan.stdout,
            plan=plan,
        )

    @trace_terraform
    @override
    async def apply(self) -> TerraformApplyDTO:
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
            return TerraformApplyDTO(
                ok=False,
                stdout=apply_res.stdout,
                feedback=apply_res.stderr or "terraform apply failed",
            )
        return TerraformApplyDTO(
            ok=True,
            stdout=apply_res.stdout,
            feedback="",
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
        if system_config.storage.state_bucket:
            self.__backend.apply(self.__workspace_path)
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

    @override
    async def state_resource_ids(self) -> list[str]:
        cfg = system_config.services.iac
        client = AuthenticatedClient(
            base_url=cfg.endpoint,
            token=cfg.token,
            timeout=httpx.Timeout(cfg.timeout),
        )
        workspace = str(self.__workspace_path)
        try:
            async with client as c:
                init_res = await self.__ensure_init(c, cfg)
                if init_res is not None:
                    raise ExceptionHandler(
                        f"terraform init failed: {init_res.stderr or 'unknown error'}",
                        502,
                    )
                state_res = await self.__run_initialized_op(
                    c,
                    state_op,
                    StateResourceIdsRequest(
                        workspace_path=workspace,
                    ),
                    cfg,
                )
                if state_res.exit_code != 0:
                    raise ExceptionHandler(
                        f"terraform state pull failed: {state_res.stderr or 'unknown error'}",
                        502,
                    )
                return json.loads(state_res.stdout)

        except httpx.TimeoutException as e:
            raise ExceptionHandler(f"IaC service timed out: {e}", 504) from e
        except httpx.RequestError as e:
            raise ExceptionHandler(f"IaC service unreachable: {e}", 502) from e

    @override
    async def scope_resource_ids(
        self,
        scope_id: str,
        terraform_provider: TerraformProvider,
    ) -> TerraformDiscoveryDTO:
        cfg = system_config.services.iac
        client = AuthenticatedClient(
            base_url=cfg.endpoint,
            token=cfg.token,
            timeout=httpx.Timeout(cfg.timeout),
        )
        workspace = str(self.__workspace_path)
        try:
            async with client as c:
                init_res = await self.__ensure_init(c, cfg)
                if init_res is not None:
                    raise ExceptionHandler(
                        f"terraform init failed: {init_res.stderr or 'unknown error'}",
                        502,
                    )
                scope_res = await self.__run_initialized_op(
                    c,
                    scope_op,
                    ScopeResourceIdsRequest(
                        workspace_path=workspace,
                        scope_id=scope_id,
                        terraform_provider=terraform_provider,
                    ),
                    cfg,
                )
                if scope_res.exit_code != 0:
                    # A failed cloud query is a normal outcome of this
                    # endpoint (scope not found, credentials issue, a
                    # provider with no inventory query at all), so the
                    # scope reads as empty and the diagnostics travel
                    # back with it: discovery finds nothing to import
                    # rather than the session failing.
                    return TerraformDiscoveryDTO(
                        resource_ids=[],
                        feedback=scope_res.stderr or "unknown error",
                    )
                return TerraformDiscoveryDTO(
                    resource_ids=json.loads(scope_res.stdout),
                )

        except httpx.TimeoutException as e:
            raise ExceptionHandler(f"IaC service timed out: {e}", 504) from e
        except httpx.RequestError as e:
            raise ExceptionHandler(f"IaC service unreachable: {e}", 502) from e

    @trace_terraform
    @override
    async def import_resource(
        self,
        address: str,
        resource_id: str,
    ) -> TerraformImportResourceDTO:
        cfg = system_config.services.iac
        client = AuthenticatedClient(
            base_url=cfg.endpoint,
            token=cfg.token,
            timeout=httpx.Timeout(cfg.timeout),
        )
        workspace = str(self.__workspace_path)
        try:
            async with client as c:
                init_res = await self.__ensure_init(c, cfg)
                if init_res is not None:
                    raise ExceptionHandler(
                        f"terraform init failed: {init_res.stderr or 'unknown error'}",
                        502,
                    )
                import_res = await self.__run_initialized_op(
                    c,
                    import_op,
                    ImportRequest(
                        workspace_path=workspace,
                        scope_id=self.__scope_id,
                        terraform_provider=self.__terraform_provider,
                        address=address,
                        resource_id=resource_id,
                    ),
                    cfg,
                )
                if import_res.exit_code != 0:
                    return TerraformImportResourceDTO(
                        ok=False,
                        stdout=import_res.stdout,
                        feedback=import_res.stderr or "terraform import failed",
                    )
                return TerraformImportResourceDTO(
                    ok=True,
                    stdout=import_res.stdout,
                    feedback="",
                )

        except httpx.TimeoutException as e:
            raise ExceptionHandler(f"IaC service timed out: {e}", 504) from e
        except httpx.RequestError as e:
            raise ExceptionHandler(f"IaC service unreachable: {e}", 502) from e

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
