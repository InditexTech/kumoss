# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""FastAPI application for the IaC reference implementation.

A raw IaC-engine executor (OpenTofu by default, Terraform via
``IAC_BINARY``): every POST enqueues a job that runs exactly one engine
command and returns ``202 Accepted`` immediately;
clients poll ``GET /v1/jobs/{job_id}`` for the raw
``{exit_code, stdout, stderr}`` result. Sequencing commands and
interpreting their output is the caller's job. Jobs targeting the same
workspace run one at a time in submission (FIFO) order. Submit-time
errors (auth, malformed body, missing workspace, missing engine
binary) are still reported synchronously on the POST; everything after
submission surfaces through the job. The two ``/v1/import/*-resource-ids``
endpoints are the exception to "raw output": their ``stdout`` is a
synthesized JSON array of resource ids rather than engine output.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Response, Security, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import engine as tf
from .auth import verify_bearer_token
from .cloud_cli import CloudCli
from .config import Config, engine_available
from .jobs import JobRegistry, WorkspaceQueue
from .log_context import (
    configure_logging,
    request_id_var,
    set_request_id,
    set_workspace,
)
from .models import (
    ApplyRequest,
    Health,
    ImportRequest,
    InitRequest,
    Job,
    JobAccepted,
    JobKind,
    LoginError,
    MissingCredentialError,
    OperationResult,
    PlanRequest,
    Problem,
    ScopeResourceIdsRequest,
    ShowRequest,
    StateResourceIdsRequest,
    ValidateRequest,
)

logger = logging.getLogger(__name__)

config = Config.from_env()
workspace_queue = WorkspaceQueue()
jobs = JobRegistry(ttl_seconds=config.job_ttl, workspace_queue=workspace_queue)
cloud = CloudCli(config)
bearer_scheme = HTTPBearer(auto_error=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(config.log_level)

    tf.set_timeout(config.subprocess_timeout)
    engine_ok = engine_available(config.iac_binary)
    logger.info(
        "iac service starting engine_available=%s binary=%s auth_enabled=%s",
        engine_ok,
        config.iac_binary,
        bool(config.expected_token),
    )

    try:
        # Partial credentials are a deployment mistake: refuse to boot
        # before any CLI is invoked. Then log into every ready provider
        # without retries so a broken credential surfaces at once.
        cloud.validate_credentials()
        await cloud.login(retries=0)
        logger.info("iac service startup complete")
    except MissingCredentialError as exc:
        # Deployment misconfiguration: the message already lists every
        # missing variable, so a traceback would only add noise.
        logger.error("iac service startup failed, incomplete credentials: %s", exc)
        raise
    except LoginError as exc:
        # Credentials are complete but a cloud CLI rejected them (revoked
        # secret, wrong tenant, expired key). Same reasoning: no traceback.
        logger.error("iac service startup failed, cloud login rejected: %s", exc)
        raise
    except Exception:
        logger.exception("iac service startup failed")
        raise

    yield
    # Job records are in-memory only: cancelling here marks unfinished
    # jobs failed(503), and a restart forgets them entirely (clients see
    # 404 and must resubmit).
    await jobs.shutdown()
    logger.info("iac service shutting down")


app = FastAPI(
    title="Nebula IaC Service",
    version="1.1.0",
    description="Reference implementation of contracts/openapi/iac.v1.yaml.",
    lifespan=lifespan,
)


@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    rid = set_request_id(request.headers.get("x-request-id"))
    t0 = time.monotonic()
    logger.info("%s %s started", request.method, request.url.path)
    response = await call_next(request)
    elapsed = time.monotonic() - t0
    logger.info(
        "%s %s completed status=%d elapsed=%.2fs",
        request.method,
        request.url.path,
        response.status_code,
        elapsed,
    )
    response.headers["x-request-id"] = rid
    return response


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


def _problem(status_code: int, title: str, detail: str | None = None) -> JSONResponse:
    payload = Problem(
        type="about:blank", title=title, status=status_code, detail=detail
    ).model_dump(exclude_none=True)
    return JSONResponse(
        status_code=status_code,
        content=payload,
        media_type="application/problem+json",
    )


def _http_reason(code: int) -> str:
    try:
        return HTTPStatus(code).phrase
    except ValueError:
        return "HTTP error"


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return _problem(exc.status_code, _http_reason(exc.status_code), exc.detail)


@app.exception_handler(StarletteHTTPException)
async def starlette_http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    return _problem(exc.status_code, _http_reason(exc.status_code), exc.detail)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    logger.warning(
        "request validation error path=%s detail=%s", request.url.path, str(exc)[:300]
    )
    return _problem(422, "Unprocessable Content", str(exc))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # The traceback is in the log under this request id; the exception
    # text itself may carry paths or CLI output and stays server-side.
    logger.exception("unhandled exception %s %s", request.method, request.url.path)
    return _problem(
        500,
        "Internal server error",
        f"Unexpected error; see the service log for request_id={request_id_var.get()}.",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/healthz", response_model=Health, tags=["ops"])
async def healthz() -> Health:
    return Health(status="ok")


def _check_submit_preconditions(
    workspace_path: str, credentials: HTTPAuthorizationCredentials | None
) -> Path:
    """Submit-time checks: auth, engine binary, workspace existence.

    Everything that fails after these (the engine command itself)
    surfaces through the job instead.
    """
    verify_bearer_token(config, credentials)

    if not engine_available(config.iac_binary):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"IaC engine binary '{config.iac_binary}' not found "
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
    set_workspace(str(workspace))
    return workspace


def _result(r: tf.CommandResult) -> OperationResult:
    return OperationResult(exit_code=r.exit_code, stdout=r.stdout, stderr=r.stderr)


def _submit(
    kind: JobKind,
    workspace: Path,
    response: Response,
    pipeline: Callable[[], Awaitable[OperationResult]],
) -> JobAccepted:
    """Enqueue one engine command as a job and point at its resource."""
    record = jobs.submit(
        kind=kind,
        workspace=workspace,
        pipeline=pipeline,
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
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> JobAccepted:
    workspace = _check_submit_preconditions(body.workspace_path, credentials)

    async def _pipeline() -> OperationResult:
        env = await cloud.scope_env(body.scope_id)
        return _result(
            await tf.init(
                config.iac_binary,
                workspace,
                backend_config=config.backend_config,
                env=env,
            )
        )

    return _submit("init", workspace, response, _pipeline)


@app.post(
    "/v1/validate",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["validate"],
)
async def validate(
    body: ValidateRequest,
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> JobAccepted:
    workspace = _check_submit_preconditions(body.workspace_path, credentials)

    async def _pipeline() -> OperationResult:
        env = await cloud.scope_env(body.scope_id)
        return _result(await tf.validate(config.iac_binary, workspace, env=env))

    return _submit("validate", workspace, response, _pipeline)


@app.post(
    "/v1/plan",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["plan"],
)
async def plan(
    body: PlanRequest,
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> JobAccepted:
    workspace = _check_submit_preconditions(body.workspace_path, credentials)

    async def _pipeline() -> OperationResult:
        env = await cloud.scope_env(body.scope_id)
        return _result(
            await tf.plan(
                config.iac_binary, workspace, body.targets, body.plan_file, env=env
            )
        )

    return _submit("plan", workspace, response, _pipeline)


@app.post(
    "/v1/show",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["show"],
)
async def show(
    body: ShowRequest,
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> JobAccepted:
    workspace = _check_submit_preconditions(body.workspace_path, credentials)

    async def _pipeline() -> OperationResult:
        env = await cloud.scope_env(body.scope_id)
        return _result(
            await tf.show_plan_json(
                config.iac_binary, workspace, body.plan_file, env=env
            )
        )

    return _submit("show", workspace, response, _pipeline)


@app.post(
    "/v1/apply",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["apply"],
)
async def apply(
    body: ApplyRequest,
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> JobAccepted:
    workspace = _check_submit_preconditions(body.workspace_path, credentials)

    async def _pipeline() -> OperationResult:
        env = await cloud.scope_env(body.scope_id)
        return _result(
            await tf.apply(config.iac_binary, workspace, body.plan_file, env=env)
        )

    return _submit("apply", workspace, response, _pipeline)


@app.post(
    "/v1/import",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["import"],
)
async def import_resource(
    body: ImportRequest,
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> JobAccepted:
    workspace = _check_submit_preconditions(body.workspace_path, credentials)

    async def _pipeline() -> OperationResult:
        env = await cloud.scope_env(body.scope_id)
        return _result(
            await tf.import_resource(
                config.iac_binary, workspace, body.address, body.resource_id, env=env
            )
        )

    return _submit("import", workspace, response, _pipeline)


@app.post(
    "/v1/import/state-resource-ids",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["import"],
)
async def state_resource_ids(
    body: StateResourceIdsRequest,
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> JobAccepted:
    workspace = _check_submit_preconditions(body.workspace_path, credentials)

    async def _pipeline() -> OperationResult:
        env = await cloud.scope_env(body.scope_id)
        return _result(
            await cloud.state_resource_ids(config.iac_binary, workspace, env)
        )

    return _submit("state_resource_ids", workspace, response, _pipeline)


@app.post(
    "/v1/import/scope-resource-ids",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["import"],
)
async def scope_resource_ids(
    body: ScopeResourceIdsRequest,
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> JobAccepted:
    workspace = _check_submit_preconditions(body.workspace_path, credentials)
    if not cloud.cli_available(body.terraform_provider):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Cloud CLI '{cloud.cli_binary(body.terraform_provider)}' "
                f"for provider '{body.terraform_provider}' not found in PATH "
                "on the IaC service."
            ),
        )

    async def _pipeline() -> OperationResult:
        # The only endpoint that shells out to the cloud CLI itself (az graph,
        # gcloud asset, aws tagging API), so the only one that needs a live
        # CLI session. Engine commands authenticate from the env vars that
        # scope_env injects and never read the CLI login.
        await cloud.ensure_login()
        return _result(
            await cloud.scope_resource_ids(body.terraform_provider, body.scope_id)
        )

    return _submit("scope_resource_ids", workspace, response, _pipeline)


@app.get("/v1/jobs/{job_id}", response_model=Job, tags=["jobs"])
async def get_job(
    job_id: UUID,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> Job:
    verify_bearer_token(config, credentials)
    record = jobs.get(str(job_id))
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown or expired job: {job_id}",
        )
    return record.to_model()
