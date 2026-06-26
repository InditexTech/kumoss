# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Annotated
from fastapi.responses import JSONResponse
from fastapi import APIRouter, Body, HTTPException

from src.application.factory import HandlerFactory
from src.domains.services.database_service import DatabaseService
from src.infrastructure.filesystem import GitUtils
from src.shared.config import system_config

# from src.shared.constants import SessionStatus
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
    try:
        session = await DatabaseService.get_session(session_id)
        if not session:
            raise HTTPException(
                status_code=404, detail=f"Session {session_id} not found."
            )
        await GitUtils(system_config.git.provider).complete_pr(session.repo_uri, id)
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
) -> JSONResponse:
    session = await DatabaseService.get_session(session_id)
    pr_svc = HandlerFactory(session_ctx=session).get_pull_request_service()
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")
    # if session.status != SessionStatus.REPORT.value:
    #     raise HTTPException(
    #         status_code=409, detail=f"Session {session_id} is {session.status}."
    #     )

    try:
        pr_details = await pr_svc.create_pr(session)
        await DatabaseService.set_pull_request_url(session_id, pr_details.url)
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)

    # TODO: define when a session is completed
    # await DatabaseService.mark_completed(session_id)

    return JSONResponse(
        content={"id": pr_details.id, "status": pr_details.status},
        status_code=200,
    )
