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
errors (auth, malformed body, missing workspace, missing engine
binary) are still reported synchronously on the POST; everything after
submission surfaces through the job.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import cloud_cli
from . import terraform as tf
from .auth import verify_bearer_token
from .config import Config, terraform_available
from .jobs import JobRegistry, WorkspaceQueue
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
)


# Console logging for the service's own loggers ("iac.*": engine
# operations, config warnings). uvicorn only configures its own
# loggers, so without this handler the operation logs would be
# invisible at the default log level.
_iac_logger = logging.getLogger("iac")
if not _iac_logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    _iac_logger.addHandler(_handler)
    _iac_logger.setLevel(logging.INFO)

config = Config.from_env()
workspace_queue = WorkspaceQueue()
jobs = JobRegistry(ttl_seconds=config.job_ttl, workspace_queue=workspace_queue)


async def _log_engine_version() -> None:
    """Report which IaC engine this service runs (path + version).

    Diagnostics only: the binary's resolvability is already asserted by
    Config at import time, so a probe failure is logged, never fatal.
    Goes through the "iac" logger, whose stderr handler is configured
    above independently of uvicorn's logging setup.
    """
    logger = logging.getLogger("iac.engine")
    resolved = shutil.which(config.terraform_binary)
    try:
        proc = await asyncio.create_subprocess_exec(
            config.terraform_binary,
            "version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, _ = await proc.communicate()
        version = (
            stdout_bytes.decode("utf-8", errors="replace").splitlines() or ["unknown"]
        )[0]
    except OSError as exc:
        logger.warning("IaC engine %s: version probe failed: %s", resolved, exc)
        return
    logger.info("IaC engine: %s — %s", resolved, version)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _log_engine_version()
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
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return _problem(exc.status_code, exc.detail or "HTTP error")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return _problem(422, "Request validation failed", str(exc))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return _problem(500, "Internal server error", str(exc))


@app.get("/healthz", response_model=Health, tags=["ops"])
async def healthz() -> Health:
    return Health(status="ok")


def _check_submit_preconditions(workspace_path: str, authorization: str | None) -> Path:
    """Submit-time checks: auth, engine binary, workspace existence.

    Everything that fails after these (the engine command itself)
    surfaces through the job instead.
    """
    verify_bearer_token(config, authorization)

    if not terraform_available(config.terraform_binary):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"IaC engine binary '{config.terraform_binary}' not found "
                "in PATH on the IaC service."
            ),
        )

    workspace = Path(workspace_path)
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


async def _run_op(command: Awaitable[tf.CommandResult]) -> OperationResult:
    result = await command
    return OperationResult(
        exit_code=result.exit_code, stdout=result.stdout, stderr=result.stderr
    )


def _submit(
    kind: JobKind,
    workspace: Path,
    response: Response,
    command: Callable[[], Awaitable[tf.CommandResult]],
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
)
async def init(
    body: InitRequest,
    response: Response,
    authorization: str | None = Header(default=None),
) -> JobAccepted:
    workspace = _check_submit_preconditions(body.workspace_path, authorization)
    return _submit(
        "init",
        workspace,
        response,
        lambda: tf.init(config.terraform_binary, workspace),
    )


@app.post(
    "/v1/validate",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["validate"],
)
async def validate(
    body: ValidateRequest,
    response: Response,
    authorization: str | None = Header(default=None),
) -> JobAccepted:
    workspace = _check_submit_preconditions(body.workspace_path, authorization)
    return _submit(
        "validate",
        workspace,
        response,
        lambda: tf.validate(config.terraform_binary, workspace),
    )


@app.post(
    "/v1/plan",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["plan"],
)
async def plan(
    body: PlanRequest,
    response: Response,
    authorization: str | None = Header(default=None),
) -> JobAccepted:
    workspace = _check_submit_preconditions(body.workspace_path, authorization)
    return _submit(
        "plan",
        workspace,
        response,
        lambda: tf.plan(
            config.terraform_binary, workspace, body.targets, body.plan_file
        ),
    )


@app.post(
    "/v1/show",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["show"],
)
async def show(
    body: ShowRequest,
    response: Response,
    authorization: str | None = Header(default=None),
) -> JobAccepted:
    workspace = _check_submit_preconditions(body.workspace_path, authorization)
    return _submit(
        "show",
        workspace,
        response,
        lambda: tf.show_plan_json(config.terraform_binary, workspace, body.plan_file),
    )


@app.post(
    "/v1/apply",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["apply"],
)
async def apply(
    body: ApplyRequest,
    response: Response,
    authorization: str | None = Header(default=None),
) -> JobAccepted:
    workspace = _check_submit_preconditions(body.workspace_path, authorization)
    return _submit(
        "apply",
        workspace,
        response,
        lambda: tf.apply(config.terraform_binary, workspace, body.plan_file),
    )


@app.post(
    "/v1/import",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["import"],
)
async def import_resource(
    body: ImportRequest,
    response: Response,
    authorization: str | None = Header(default=None),
) -> JobAccepted:
    workspace = _check_submit_preconditions(body.workspace_path, authorization)
    return _submit(
        "import",
        workspace,
        response,
        lambda: tf.import_resource(
            config.terraform_binary, workspace, body.address, body.resource_id
        ),
    )


@app.post(
    "/v1/import/state-resource-ids",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["import"],
)
async def state_resource_ids(
    body: StateResourceIdsRequest,
    response: Response,
    authorization: str | None = Header(default=None),
) -> JobAccepted:
    workspace = _check_submit_preconditions(body.workspace_path, authorization)
    record = jobs.submit(
        kind="state_resource_ids",
        workspace=workspace,
        pipeline=lambda: _state_resource_ids_op(workspace),
    )
    response.headers["Location"] = f"/v1/jobs/{record.job_id}"
    return JobAccepted(job_id=record.job_id)


async def _state_resource_ids_op(workspace: Path) -> OperationResult:
    result = await tf.state_pull(config.terraform_binary, workspace)
    if not result.ok:
        return OperationResult(
            exit_code=result.exit_code, stdout="", stderr=result.stderr
        )
    ids = tf.extract_managed_resource_ids(result.stdout)
    return OperationResult(exit_code=0, stdout=json.dumps(ids), stderr="")


@app.post(
    "/v1/import/scope-resource-ids",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["import"],
)
async def scope_resource_ids(
    body: ScopeResourceIdsRequest,
    response: Response,
    authorization: str | None = Header(default=None),
) -> JobAccepted:
    workspace = _check_submit_preconditions(body.workspace_path, authorization)
    if not cloud_cli.cli_available(body.terraform_provider):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Cloud CLI '{cloud_cli.CLI_BINARIES[body.terraform_provider]}' "
                f"for provider '{body.terraform_provider}' not found in PATH "
                "on the IaC service."
            ),
        )
    return _submit(
        "scope_resource_ids",
        workspace,
        response,
        lambda: cloud_cli.list_resource_ids(body.terraform_provider, body.scope_id),
    )


@app.get("/v1/jobs/{job_id}", response_model=Job, tags=["jobs"])
async def get_job(
    job_id: UUID,
    authorization: str | None = Header(default=None),
) -> Job:
    verify_bearer_token(config, authorization)
    record = jobs.get(str(job_id))
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown or expired job: {job_id}",
        )
    return record.to_model()
