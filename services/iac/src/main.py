# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""FastAPI application for the IaC reference implementation.

Every terraform POST enqueues a job and returns ``202 Accepted``
immediately; clients poll ``GET /v1/jobs/{job_id}`` for the result.
Jobs targeting the same workspace run one at a time in submission
(FIFO) order. Submit-time errors (auth, malformed body, missing
workspace, missing terraform binary) are still reported synchronously
on the POST; everything after submission surfaces through the job.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import terraform as tf
from .auth import verify_bearer_token
from .config import Config, have_cloud_credentials, terraform_available
from .jobs import JobRegistry, WorkspaceQueue
from .models import (
    ApplyRequest,
    ApplyResult,
    Health,
    ImportRequest,
    ImportResult,
    Job,
    JobAccepted,
    Problem,
    ValidateRequest,
    ValidateResult,
)


config = Config.from_env()
workspace_queue = WorkspaceQueue()
jobs = JobRegistry(ttl_seconds=config.job_ttl, workspace_queue=workspace_queue)


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    """Submit-time checks: auth, terraform binary, workspace existence.

    Everything that fails after these (the terraform pipeline itself)
    surfaces through the job instead.
    """
    verify_bearer_token(config, authorization)

    if not terraform_available(config.terraform_binary):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Terraform binary '{config.terraform_binary}' not found "
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
    record = jobs.submit(
        kind="validate",
        workspace=workspace,
        pipeline=lambda: _run_validate(body, workspace),
    )
    response.headers["Location"] = f"/v1/jobs/{record.job_id}"
    return JobAccepted(job_id=record.job_id)


async def _run_validate(body: ValidateRequest, workspace: Path) -> ValidateResult:
    init_result = await tf.init(config.terraform_binary, workspace)
    if not init_result.ok:
        return ValidateResult(
            validation=False,
            feedback=init_result.stderr or "terraform init failed",
            terraform_plan="",
            terraform_targets=body.targets,
        )

    validate_result = await tf.validate(config.terraform_binary, workspace)
    if not validate_result.ok:
        return ValidateResult(
            validation=False,
            feedback=validate_result.stderr or "terraform validate failed",
            terraform_plan="",
            terraform_targets=body.targets,
        )

    # Skip `plan` when no cloud credentials are visible; plan would just
    # fail with auth errors that aren't useful feedback for the caller.
    if not have_cloud_credentials() and not config.allow_plan_without_creds:
        return ValidateResult(
            validation=True,
            feedback=(
                "terraform validate passed; plan skipped because no cloud "
                "provider credentials were configured for the IaC "
                "service. Set ARM_*, GOOGLE_*, or AWS_* env vars (or set "
                "NEBULA_IAC_ALLOW_PLAN_WITHOUT_CREDS=true to attempt "
                "plan anyway)."
            ),
            terraform_plan="",
            terraform_targets=body.targets,
        )

    plan_file = tf.random_plan_filename()
    plan_result = await tf.plan(
        config.terraform_binary, workspace, body.targets, plan_file
    )
    if not plan_result.ok:
        return ValidateResult(
            validation=False,
            feedback=plan_result.stderr or "terraform plan failed",
            terraform_plan=plan_result.stdout,
            terraform_targets=body.targets,
        )

    if body.get_drift:
        show_result = await tf.show_plan_json(
            config.terraform_binary, workspace, plan_file
        )
        if show_result.ok:
            drift = tf.parse_drift(show_result.stdout)
            if drift:
                return ValidateResult(
                    validation=False,
                    feedback=str(drift),
                    terraform_plan=plan_result.stdout,
                    terraform_targets=body.targets,
                )

    return ValidateResult(
        validation=True,
        feedback="",
        terraform_plan=plan_result.stdout,
        terraform_targets=body.targets,
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
    record = jobs.submit(
        kind="apply",
        workspace=workspace,
        pipeline=lambda: _run_apply(body, workspace),
    )
    response.headers["Location"] = f"/v1/jobs/{record.job_id}"
    return JobAccepted(job_id=record.job_id)


async def _run_apply(body: ApplyRequest, workspace: Path) -> ApplyResult:
    init_result = await tf.init(config.terraform_binary, workspace)
    if not init_result.ok:
        return ApplyResult(
            success=False,
            feedback=init_result.stderr or "terraform init failed",
            terraform_output="",
        )

    plan_file = tf.random_plan_filename()
    plan_result = await tf.plan(
        config.terraform_binary, workspace, body.targets, plan_file
    )
    if not plan_result.ok:
        return ApplyResult(
            success=False,
            feedback=plan_result.stderr or "terraform plan failed",
            terraform_output=plan_result.stdout,
        )

    apply_result = await tf.apply(config.terraform_binary, workspace, plan_file)
    return ApplyResult(
        success=apply_result.ok,
        feedback=apply_result.stderr if not apply_result.ok else "",
        terraform_output=apply_result.stdout,
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
    record = jobs.submit(
        kind="import",
        workspace=workspace,
        pipeline=lambda: _run_import(body, workspace),
    )
    response.headers["Location"] = f"/v1/jobs/{record.job_id}"
    return JobAccepted(job_id=record.job_id)


async def _run_import(body: ImportRequest, workspace: Path) -> ImportResult:
    init_result = await tf.init(config.terraform_binary, workspace)
    if not init_result.ok:
        return ImportResult(
            success=False,
            feedback=init_result.stderr or "terraform init failed",
        )

    result = await tf.import_resource(
        config.terraform_binary, workspace, body.address, body.resource_id
    )
    return ImportResult(
        success=result.ok,
        feedback=result.stderr if not result.ok else "",
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
