# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""FastAPI application for the IaC reference implementation.

A raw IaC-engine executor (OpenTofu by default): every POST enqueues a
job that runs exactly one engine command and returns ``202 Accepted``
immediately; clients poll ``GET /v1/jobs/{job_id}`` for the raw
``{exit_code, stdout, stderr}`` result. Sequencing commands and
interpreting their output is the caller's job. Jobs targeting the same
workspace run one at a time in submission (FIFO) order. Submit-time
errors (auth, malformed body, missing workspace) are still reported
synchronously on the POST; everything after submission surfaces
through the job.

``init``, ``plan`` and ``apply`` run scoped to the request's
``scope_id``, injected into the engine's environment under the
variable its ``terraform_provider`` selects. ``validate`` and ``show``
take no scope, so their bodies declare none and reject one.

``init`` always reconfigures the backend, and passes
``IAC_BACKEND_CONFIG`` to ``-backend-config`` when the deployment sets
one; the backend itself comes from the workspace's own configuration,
which the caller is free to have written an override for.

``import`` is scoped the same way as ``plan`` and ``apply``.
``/v1/import/state-resource-ids`` runs ``state pull`` and answers a
JSON array of the resource IDs the state tracks.
``/v1/import/scope-resource-ids`` is the one endpoint that runs no
engine command at all: it queries the cloud's own inventory API and
answers a JSON array of the resource IDs under the request's scope
whose lifecycle no other control plane owns.
"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials

from .auth import bearer_scheme, verify_bearer_token
from .config import Config
from .discovery import DiscoveryError, ScopeDiscovery
from .engine import CommandResult, IacEngine
from .jobs import JobRegistry, Pipeline, WorkspaceQueue
from .models import (
    ApplyRequest,
    Health,
    ImportRequest,
    InitRequest,
    Job,
    JobAccepted,
    JobKind,
    OperationResult,
    PlanRequest,
    Problem,
    ScopeResourceIdsRequest,
    ShowRequest,
    StateResourceIdsRequest,
    ValidateRequest,
    WorkspaceRequest,
)
from .state import StateResourceIds


config = Config.from_env()
config.setup_logging()
workspace_queue = WorkspaceQueue()
jobs = JobRegistry(ttl_seconds=config.job_ttl, workspace_queue=workspace_queue)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    # Job records are in-memory only: cancelling here marks unfinished
    # jobs failed(503), and a restart forgets them entirely (clients see
    # 404 and must resubmit).
    await jobs.shutdown()


app = FastAPI(
    title="Nebula IaC Service",
    version="1.0.0",
    description="Reference implementation of contracts/openapi/iac.v1.yaml.",
    lifespan=lifespan,
)


def _problem(
    status_code: int,
    title: str,
    detail: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    payload = Problem(
        type="about:blank", title=title, status=status_code, detail=detail
    ).model_dump(exclude_none=True)
    return JSONResponse(
        status_code=status_code,
        content=payload,
        media_type="application/problem+json",
        headers=headers,
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    return _problem(exc.status_code, exc.detail or "HTTP error", headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return _problem(422, "Request validation failed", str(exc))


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    _request: Request, exc: Exception
) -> JSONResponse:
    return _problem(500, "Internal server error", str(exc))


@app.get("/healthz", response_model=Health, tags=["ops"])
async def healthz() -> Health:
    return Health(status="ok")


async def require_bearer_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> None:
    """Reject the request unless it carries the configured bearer token."""
    verify_bearer_token(config, credentials)


async def resolve_workspace(body: WorkspaceRequest) -> Path:
    """Resolve the submit body's ``workspace_path`` to an existing directory.

    Binds to the shared ``WorkspaceRequest`` base so one dependency
    serves all five submit endpoints. The parameter must stay named
    ``body`` to match the endpoints': FastAPI only collapses a
    dependency's body param into the endpoint's documented body when
    the two share a name, and embeds both under separate keys if not.

    Everything that fails after this (the engine command itself)
    surfaces through the job instead.
    """
    workspace = Path(body.workspace_path)
    try:
        is_dir = workspace.is_dir()
    except OSError as exc:
        # Path is malformed for the host OS (too long, invalid chars, etc.)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"workspace_path is not a usable filesystem path: {exc}",
        ) from exc
    if not is_dir:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"workspace_path does not exist or is not a directory: {workspace}",
        )
    return workspace


def resolve_engine() -> IacEngine:
    """The IaC engine the current configuration selects."""
    return IacEngine(binary=config.iac_binary, backend_config=config.backend_config)


def resolve_discovery() -> ScopeDiscovery:
    """The scope discovery the service's own environment configures."""
    return ScopeDiscovery(os.environ)


Authenticated = Depends(require_bearer_token)
Workspace = Annotated[Path, Depends(resolve_workspace)]
Engine = Annotated[IacEngine, Depends(resolve_engine)]
Discovery = Annotated[ScopeDiscovery, Depends(resolve_discovery)]


async def _run_op(command: Awaitable[CommandResult]) -> OperationResult:
    result = await command
    return OperationResult(
        exit_code=result.exit_code, stdout=result.stdout, stderr=result.stderr
    )


def _submit_pipeline(
    kind: JobKind,
    workspace: Path,
    response: Response,
    pipeline: Pipeline,
) -> JobAccepted:
    """Enqueue one job pipeline and point at its resource."""
    record = jobs.submit(kind=kind, workspace=workspace, pipeline=pipeline)
    response.headers["Location"] = f"/v1/jobs/{record.job_id}"
    return JobAccepted(job_id=record.job_id)


def _submit(
    kind: JobKind,
    workspace: Path,
    response: Response,
    command: Callable[[], Awaitable[CommandResult]],
) -> JobAccepted:
    """Enqueue one engine command as a job and point at its resource."""
    return _submit_pipeline(kind, workspace, response, lambda: _run_op(command()))


async def _state_resource_ids(engine: IacEngine, workspace: Path) -> OperationResult:
    result = await engine.state_pull(workspace)
    if result.exit_code != 0:
        return OperationResult(
            exit_code=result.exit_code, stdout="", stderr=result.stderr
        )
    try:
        ids = StateResourceIds().read(result.stdout)
    except ValueError as exc:
        return OperationResult(exit_code=1, stdout="", stderr=str(exc))
    return OperationResult(exit_code=0, stdout=json.dumps(ids), stderr=result.stderr)


async def _scope_resource_ids(
    discovery: ScopeDiscovery, terraform_provider: str, scope_id: str
) -> OperationResult:
    try:
        ids = await discovery.resource_ids(terraform_provider, scope_id)
    except DiscoveryError as exc:
        return OperationResult(exit_code=1, stdout="", stderr=str(exc))
    if ids is None:
        return OperationResult(
            exit_code=2,
            stdout="",
            stderr=f"no scope discovery for provider '{terraform_provider}'",
        )
    return OperationResult(exit_code=0, stdout=json.dumps(ids), stderr="")


@app.post(
    "/v1/init",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["init"],
    dependencies=[Authenticated],
)
async def init(
    body: InitRequest,
    workspace: Workspace,
    engine: Engine,
    response: Response,
) -> JobAccepted:
    env = engine.scope_env(body.terraform_provider, body.scope_id)
    return _submit(
        "init",
        workspace,
        response,
        lambda: engine.init(workspace, env),
    )


@app.post(
    "/v1/validate",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["validate"],
    dependencies=[Authenticated],
)
async def validate(
    body: ValidateRequest,  # pyright: ignore[reportUnusedParameter]
    workspace: Workspace,
    engine: Engine,
    response: Response,
) -> JobAccepted:
    return _submit(
        "validate",
        workspace,
        response,
        lambda: engine.validate(workspace),
    )


@app.post(
    "/v1/plan",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["plan"],
    dependencies=[Authenticated],
)
async def plan(
    body: PlanRequest,
    workspace: Workspace,
    engine: Engine,
    response: Response,
) -> JobAccepted:
    env = engine.scope_env(body.terraform_provider, body.scope_id)
    return _submit(
        "plan",
        workspace,
        response,
        lambda: engine.plan(workspace, body.targets, body.plan_file, env),
    )


@app.post(
    "/v1/show",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["show"],
    dependencies=[Authenticated],
)
async def show(
    body: ShowRequest,
    workspace: Workspace,
    engine: Engine,
    response: Response,
) -> JobAccepted:
    return _submit(
        "show",
        workspace,
        response,
        lambda: engine.show_plan_json(workspace, body.plan_file),
    )


@app.post(
    "/v1/apply",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["apply"],
    dependencies=[Authenticated],
)
async def apply(
    body: ApplyRequest,
    workspace: Workspace,
    engine: Engine,
    response: Response,
) -> JobAccepted:
    env = engine.scope_env(body.terraform_provider, body.scope_id)
    return _submit(
        "apply",
        workspace,
        response,
        lambda: engine.apply(workspace, body.plan_file, env),
    )


@app.post(
    "/v1/import",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["import"],
    dependencies=[Authenticated],
)
async def import_resource(
    body: ImportRequest,
    workspace: Workspace,
    engine: Engine,
    response: Response,
) -> JobAccepted:
    env = engine.scope_env(body.terraform_provider, body.scope_id)
    return _submit(
        "import",
        workspace,
        response,
        lambda: engine.import_resource(workspace, body.address, body.resource_id, env),
    )


@app.post(
    "/v1/import/state-resource-ids",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["import"],
    dependencies=[Authenticated],
)
async def state_resource_ids(
    body: StateResourceIdsRequest,  # pyright: ignore[reportUnusedParameter]
    workspace: Workspace,
    engine: Engine,
    response: Response,
) -> JobAccepted:
    return _submit_pipeline(
        "state_resource_ids",
        workspace,
        response,
        lambda: _state_resource_ids(engine, workspace),
    )


@app.post(
    "/v1/import/scope-resource-ids",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["import"],
    dependencies=[Authenticated],
)
async def scope_resource_ids(
    body: ScopeResourceIdsRequest,
    workspace: Workspace,
    discovery: Discovery,
    response: Response,
) -> JobAccepted:
    return _submit_pipeline(
        "scope_resource_ids",
        workspace,
        response,
        lambda: _scope_resource_ids(discovery, body.terraform_provider, body.scope_id),
    )


@app.get(
    "/v1/jobs/{job_id}",
    response_model=Job,
    tags=["jobs"],
    dependencies=[Authenticated],
)
async def get_job(job_id: UUID) -> Job:
    record = jobs.get(str(job_id))
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown or expired job: {job_id}",
        )
    return record.to_model()
