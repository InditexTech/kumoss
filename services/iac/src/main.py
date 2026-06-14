# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""FastAPI application for the IaC reference implementation."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import terraform as tf
from .auth import verify_bearer_token
from .config import Config, have_cloud_credentials, terraform_available
from .models import Health, Problem, ValidateRequest, ValidateResponse


config = Config.from_env()


app = FastAPI(
    title="Nebula IaC Service",
    version="1.0.0",
    description="Reference implementation of contracts/openapi/iac.v1.yaml.",
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


@app.post(
    "/v1/validate",
    response_model=ValidateResponse,
    status_code=status.HTTP_200_OK,
    tags=["validate"],
)
async def validate(
    body: ValidateRequest,
    authorization: str | None = Header(default=None),
) -> ValidateResponse:
    verify_bearer_token(config, authorization)

    if not terraform_available(config.terraform_binary):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Terraform binary '{config.terraform_binary}' not found "
                "in PATH on the IaC service."
            ),
        )

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

    init_result = await tf.init(config.terraform_binary, workspace)
    if not init_result.ok:
        return ValidateResponse(
            validation=False,
            feedback=init_result.stderr or "terraform init failed",
            terraform_plan="",
            terraform_targets=body.targets,
        )

    validate_result = await tf.validate(config.terraform_binary, workspace)
    if not validate_result.ok:
        return ValidateResponse(
            validation=False,
            feedback=validate_result.stderr or "terraform validate failed",
            terraform_plan="",
            terraform_targets=body.targets,
        )

    # Skip `plan` when no cloud credentials are visible; plan would just
    # fail with auth errors that aren't useful feedback for the caller.
    if not have_cloud_credentials() and not config.allow_plan_without_creds:
        return ValidateResponse(
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
        return ValidateResponse(
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
                return ValidateResponse(
                    validation=False,
                    feedback=str(drift),
                    terraform_plan=plan_result.stdout,
                    terraform_targets=body.targets,
                )

    return ValidateResponse(
        validation=True,
        feedback="",
        terraform_plan=plan_result.stdout,
        terraform_targets=body.targets,
    )
