# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse

from src.application.factory import ApplicationFactory
from src.domains.dto import PullRequestDTO
from src.domains.services.database_service import DatabaseService
from src.domains.services.tracer_service import tracer
from src.infrastructure.telemetry.phoenix.phoenix_tracer import PhoenixTracer
from src.shared.exceptions import ExceptionHandler

router = APIRouter(prefix="/repository", tags=["Repository Operations"])


@router.patch(
    path="/merge_pr", summary="merge the PR with ID `id` into the default branch"
)
async def complete_pr(
    session_id: Annotated[
        str,
        Body(
            description="Session id whose branch should be turned into a PR.",
            pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            embed=True,
        ),
    ],
    id: Annotated[int, Body(description="Pull Request ID.")],
) -> JSONResponse:
    uuid = UUID(session_id)
    try:
        try:
            ctx = await DatabaseService.get_session_context(uuid)
        except ExceptionHandler as e:
            raise HTTPException(status_code=e.error_code, detail=e.message)
        await ApplicationFactory.get_git_utils(ctx.repo_uri).complete_pr(id)
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)
    return JSONResponse(content="OK", status_code=200)


@router.put(path="/pr", summary="Submit the code to create a Pull Request")
async def create_pr(
    session_id: Annotated[
        str,
        Body(
            description="Session id whose branch should be turned into a PR.",
            pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            embed=True,
        ),
    ],
) -> PullRequestDTO:
    uuid = UUID(session_id)
    try:
        ctx = await DatabaseService.get_session_context(uuid)
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)
    pr_svc = ApplicationFactory(ctx).get_pull_request_service()

    tracer_token = tracer.set_current_tracer(
        tracer=PhoenixTracer(
            session_id=ctx.id,
            user_id=ctx.user_id,
            branch_name=ctx.branch_name,
            cloud=ctx.terraform_prv,
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

    # TODO: define when a session is completed
    # await DatabaseService.mark_completed(session_id)

    return pr_details


@router.post(
    path="/parse",
    summary="Parse a repository for Terraform root-module directories.",
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
