# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse

from src.api.deps import (
    assert_session_access,
    require_operation_role,
)
from src.application.factory import ApplicationFactory
from src.application.iac_requests import (
    EMBEDDED_PASSWORD_MESSAGE,
    embeds_password,
    validate_repo_uri,
)
from src.domains.dto import PullRequestDTO
from src.domains.entities import SessionContext, User
from src.domains.services.database_service import DatabaseService
from src.domains.services.tracer_service import tracer
from src.infrastructure.external.mapping_service import MappingServiceClient
from src.infrastructure.telemetry.langfuse_tracer import LangfuseTracer
from src.shared.constants import OperationRole
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
    user: Annotated[User, Depends(require_operation_role(OperationRole.DEVELOPER))],
) -> None:
    await assert_session_access(user, session_id, write=True)
    try:
        ctx = await DatabaseService.get_session_context(session_id)
        if await DatabaseService.is_session_blocked(ctx.id):
            raise HTTPException(
                status_code=409,
                detail=f"Session {ctx.id} is blocked; PR merge is not allowed.",
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
    user: Annotated[User, Depends(require_operation_role(OperationRole.DEVELOPER))],
) -> PullRequestDTO:
    await assert_session_access(user, session_id, write=True)
    try:
        ctx: SessionContext = await DatabaseService.get_session_context(session_id)
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)

    pr_svc = ApplicationFactory(ctx).get_pull_request_service()
    tracer_token = tracer.set_current_tracer(
        tracer=LangfuseTracer(
            session_id=ctx.id,
            user_id=ctx.user_id,
            branch_name=ctx.branch_name,
            providers=ctx.provider_types,
            repo_uri=ctx.repo_uri,
            root_module_path=ctx.root_module_path,
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
    dependencies=[Depends(require_operation_role(OperationRole.DEVELOPER))],
    summary="Resolve a repository and parse it for Terraform root-module directories.",
    description=(
        "Resolves `repo_uri` through the mapping service (a full HTTPS URL, "
        "or whatever identifier the mapper accepts, such as a bare "
        "repository name), clones the repository and returns the resolved "
        "`repo_url` with the Terraform root-module directories found, as "
        "POSIX paths relative to the repo root. Later calls must use the "
        "returned `repo_url`."
    ),
    responses={
        400: {
            "description": "Repository URI was rejected (unreachable or not allowed)."
        },
        404: {"description": "The mapping service could not resolve the identifier."},
        422: {
            "description": (
                "The input, or what it resolved to, is not an https:// URL "
                "without embedded credentials."
            )
        },
        502: {
            "description": "The mapping service failed, or cloning or scanning failed."
        },
        504: {"description": "The mapping service timed out."},
    },
)
async def parse_repository(
    repo_uri: Annotated[
        str,
        Body(
            description=(
                "Repository to parse: an HTTPS repository URI, or an "
                "identifier the mapping service resolves (with the bundled "
                "mapper, a bare repository name such as `my-iac`). A URI may "
                "carry a userinfo username (e.g. `https://org@dev.azure.com/...`) "
                "but must not embed a password or token."
            ),
            embed=True,
            min_length=1,
            max_length=1024,
        ),
    ],
) -> JSONResponse:
    identifier = repo_uri.strip()
    if not identifier:
        raise HTTPException(status_code=422, detail="repo_uri must not be blank.")
    # Rejected before the mapper sees it, so a pasted token never leaves
    # the core.
    if embeds_password(identifier):
        raise HTTPException(status_code=422, detail=EMBEDDED_PASSWORD_MESSAGE)
    try:
        resolved = await MappingServiceClient().resolve(identifier)
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)
    try:
        repo_url = validate_repo_uri(resolved.repo_url)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    try:
        service = ApplicationFactory.get_root_module_detection_service()
        roots = await service.detect_roots(repo_url)
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)
    return JSONResponse(
        content={"repo_url": repo_url, "roots": roots},
        status_code=200,
    )
