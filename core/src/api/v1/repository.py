# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse

from src.application.factory import ApplicationFactory
from src.domains.dto import PullRequestDTO
from src.domains.entities import SessionContext
from src.domains.services.database_service import DatabaseService
from src.domains.services.tracer_service import tracer
from src.infrastructure.telemetry.phoenix.phoenix_tracer import PhoenixTracer
from src.shared.exceptions import ExceptionHandler

router = APIRouter(prefix="/repository", tags=["Repository Operations"])


@router.put(
    path="/pr/merge",
    status_code=204,
    summary="Merge the session's latest pull request into the default branch.",
    description=(
        "Merges the most recently opened pull request of the session at "
        "the git provider. Returns no content on success."
    ),
    responses={
        404: {"description": "Unknown session, or the session has no pull requests."}
    },
)
async def complete_pr(
    session_id: Annotated[
        UUID,
        Body(
            description="Session id whose pull request should be merged.",
            embed=True,
        ),
    ],
) -> None:
    try:
        ctx = await DatabaseService.get_session_context(session_id)
        if await DatabaseService.is_session_blocked(ctx.id):
            raise HTTPException(
                status_code=409,
                detail=f"Session {ctx.id} is blocked by a failed compliance check; PR merge is not allowed.",
            )
        pr = (await DatabaseService.get_pull_requests(session_id))[-1]
        await ApplicationFactory.get_git_utils(ctx.repo_uri).complete_pr(pr.number)
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)


@router.put(
    path="/pr",
    status_code=201,
    summary="Submit the session's branch as a pull request.",
    description="Creates a pull request from the session's working branch.",
    responses={404: {"description": "Unknown session."}},
)
async def create_pr(
    session_id: Annotated[
        UUID,
        Body(
            description="Session id whose branch should be turned into a PR.",
            embed=True,
        ),
    ],
) -> PullRequestDTO:
    try:
        ctx: SessionContext = await DatabaseService.get_session_context(session_id)
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)

    pr_svc = ApplicationFactory(ctx).get_pull_request_service()
    tracer_token = tracer.set_current_tracer(
        tracer=PhoenixTracer(
            session_id=ctx.id,
            user_id=ctx.user_id,
            branch_name=ctx.branch_name,
            cloud=ctx.terraform_prv,
            repo_uri=ctx.repo_uri,
            iac_path=ctx.iac_path,
            operation=ctx.operation,
        )
    )
    try:
        pr_details = await pr_svc.create_pr()
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)
    finally:
        tracer.reset_current_tracer(tracer_token)

    return pr_details


@router.post(
    path="/parse",
    summary="Parse a repository for Terraform root-module directories.",
    description=(
        "Clones the repository and returns the Terraform root-module "
        "directories found, as POSIX paths relative to the repo root."
    ),
    responses={
        400: {
            "description": "Repository URI was rejected (unreachable or not allowed)."
        },
        502: {"description": "Cloning or scanning the repository failed."},
    },
)
async def parse_repository(
    repo_uri: Annotated[
        str,
        Body(
            description="Git-cloneable repository URI to parse for Terraform roots.",
            embed=True,
        ),
    ],
) -> JSONResponse:
    try:
        service = ApplicationFactory.get_iac_root_detection_service()
        roots = await service.detect_roots(repo_uri)
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)
    return JSONResponse(
        content={"roots": roots},
        status_code=200,
    )
