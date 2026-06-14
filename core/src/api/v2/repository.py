# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Annotated
from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, HTTPException

from src.domains.services.database_service import DatabaseService
from src.infrastructure.filesystem.git_utils import GitUtils
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging
from src.shared.utils.repo_uri import derive_project_name

router = APIRouter(prefix="/repository", tags=["Repository Operations"])


@router.patch(
    path="/approve_pr", summary="merge the PR with ID `id` into the default branch"
)
async def complete_pr(
    id: Annotated[int, Body(description="Pull Request ID.", embed=True)],
) -> JSONResponse:
    try:
        _ = await GitUtils().complete_pr(id)
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)
    return JSONResponse(content="OK", status_code=201)


@router.put(path="/pr", summary="Submit the code to create a Pull Request")
async def create_pr(
    session_id: Annotated[
        str,
        Body(
            description="Session id whose branch should be turned into a PR.",
            pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        ),
    ],
    q: Annotated[
        str, Body(description="PR title/description seed (the user's prompt)")
    ],
) -> JSONResponse:
    session = await DatabaseService.load_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")
    if session.status != "active":
        raise HTTPException(
            status_code=409, detail=f"Session {session_id} is {session.status}."
        )

    try:
        pr_details = await GitUtils(branch=session.branch_name).create_pr(
            description=q,
            repository_name=derive_project_name(session.repo_uri),
            target_branch="master",
        )
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)

    # Persist the PR URL when the DTO exposes one; PullRequestDTO currently
    # carries only pr_id + status (no URL field in the OSS reference).  We
    # check defensively so forge-specific subclasses that add a `pr_url`
    # attribute are handled automatically.
    pr_url = getattr(pr_details, "pr_url", None)
    if pr_url:
        await DatabaseService.set_pull_request_url(session_id, pr_url)
    else:
        logging.warning(
            f"PullRequestDTO for session {session_id} has no pr_url; "
            "pull_request_url column left NULL. "
            "Extend PullRequestDTO with a pr_url field in your forge integration."
        )
    await DatabaseService.mark_completed(session_id)
    return JSONResponse(
        content={"id": pr_details.pr_id, "status": pr_details.status},
        status_code=201,
    )
