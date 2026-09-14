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

Every command runs scoped to the request's ``scope_id``, injected into
the engine's environment under the variable its ``terraform_provider``
selects.

The ``/v1/import`` endpoints are unimplemented: they answer 501
without inspecting the request.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials

from . import engine
from .auth import bearer_scheme, verify_bearer_token
from .config import Config, setup_logging
from .jobs import JobRegistry, WorkspaceQueue
from .models import (
    ApplyRequest,
    Health,
    InitRequest,
    Job,
    JobAccepted,
    JobKind,
    OperationResult,
    PlanRequest,
    Problem,
    ShowRequest,
    ValidateRequest,
    WorkspaceRequest,
)


config = Config.from_env()
setup_logging(config)
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


def _problem(status_code: int, title: str, detail: str | None = None) -> JSONResponse:
    payload = Problem(
        type="about:blank", title=title, status=status_code, detail=detail
    ).model_dump(exclude_none=True)
    return JSONResponse(
        status_code=status_code,
        content=payload,
        media_type="application/problem+json",
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    return _problem(exc.status_code, exc.detail or "HTTP error")


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


Authenticated = Depends(require_bearer_token)
Workspace = Annotated[Path, Depends(resolve_workspace)]


async def _run_op(command: Awaitable[engine.CommandResult]) -> OperationResult:
    result = await command
    return OperationResult(
        exit_code=result.exit_code, stdout=result.stdout, stderr=result.stderr
    )


def _submit(
    kind: JobKind,
    workspace: Path,
    response: Response,
    command: Callable[[], Awaitable[engine.CommandResult]],
) -> JobAccepted:
    """Enqueue one engine command as a job and point at its resource."""
    record = jobs.submit(
        kind=kind,
        workspace=workspace,
        pipeline=lambda: _run_op(command()),
    )
    response.headers["Location"] = f"/v1/jobs/{record.job_id}"
    return JobAccepted(job_id=record.job_id)


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
    response: Response,
) -> JobAccepted:
    env = engine.scope_env(body.terraform_provider, body.scope_id)
    return _submit(
        "init",
        workspace,
        response,
        lambda: engine.init(config.iac_binary, workspace, env),
    )


@app.post(
    "/v1/validate",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["validate"],
    dependencies=[Authenticated],
)
async def validate(
    body: ValidateRequest,
    workspace: Workspace,
    response: Response,
) -> JobAccepted:
    env = engine.scope_env(body.terraform_provider, body.scope_id)
    return _submit(
        "validate",
        workspace,
        response,
        lambda: engine.validate(config.iac_binary, workspace, env),
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
    response: Response,
) -> JobAccepted:
    env = engine.scope_env(body.terraform_provider, body.scope_id)
    return _submit(
        "plan",
        workspace,
        response,
        lambda: engine.plan(
            config.iac_binary, workspace, body.targets, body.plan_file, env
        ),
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
    response: Response,
) -> JobAccepted:
    env = engine.scope_env(body.terraform_provider, body.scope_id)
    return _submit(
        "show",
        workspace,
        response,
        lambda: engine.show_plan_json(
            config.iac_binary, workspace, body.plan_file, env
        ),
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
    response: Response,
) -> JobAccepted:
    env = engine.scope_env(body.terraform_provider, body.scope_id)
    return _submit(
        "apply",
        workspace,
        response,
        lambda: engine.apply(config.iac_binary, workspace, body.plan_file, env),
    )


def _import_not_implemented() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Import is not implemented by this service.",
    )


@app.post(
    "/v1/import",
    response_model=Problem,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    tags=["import"],
)
async def import_resource() -> Problem:
    _import_not_implemented()


@app.post(
    "/v1/import/state-resource-ids",
    response_model=Problem,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    tags=["import"],
)
async def state_resource_ids() -> Problem:
    _import_not_implemented()


@app.post(
    "/v1/import/scope-resource-ids",
    response_model=Problem,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    tags=["import"],
)
async def scope_resource_ids() -> Problem:
    _import_not_implemented()


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
