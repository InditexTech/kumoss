# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from datetime import datetime, timezone
from uuid import UUID, uuid4

from src.application.exceptions import (
    SessionConflict,
    SessionForbidden,
    SessionTerminal,
)
from src.application.iac_requests import _BaseIacRequest
from src.domains.entities import Session
from src.domains.services.database_service import DatabaseService
from src.infrastructure.database.models import Workspace
from src.shared.constants import SessionStatus
from src.shared.utils import repo_uri


class SessionOrchestrationService:
    """Resolves an incoming request into an in-flight SessionContext.

    Caller MUST pair `resolve(...)` with `release(session_id)` in a
    try/finally to clear the in_flight flag.
    """

    def _new_branch_name(self) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        return f"Nebula/{ts}"

    async def resolve(
        self, request: _BaseIacRequest, operation_type: str = "generate"
    ) -> Session:
        if request.repo_uri is not None:
            return await self._create(request, operation_type)
        return await self._load(request)

    async def _create(
        self, request: _BaseIacRequest, operation_type: str = "generate"
    ) -> Session:
        sid = uuid4()
        branch = self._new_branch_name()
        _ = await DatabaseService.create_session(
            session_id=sid,
            user_id=request.user_id,
            repo_uri=request.repo_uri,
            cloud=request.cloud,
            branch_name=branch,
            query=request.q,
            iac_path=request.iac_path,
        )
        if not await DatabaseService.acquire_in_flight(str(sid)):
            # Should not happen on a fresh row, but defend anyway.
            raise SessionConflict("Failed to acquire in_flight lock on new session.")
        return Session(
            id=sid,
            user_id=request.user_id,
            repo_uri=repo_uri,
            cloud=request.cloud,
            branch_name=branch,
            iac_path=request.iac_path,
        )
        # return SessionContext(
        #     session_id=sid,
        #     user_id=request.user_id,
        #     repo_uri=request.repo_uri,
        #     cloud=request.cloud,
        #     environment=request.environment,
        #     branch_name=branch,
        #     history=[],
        #     is_first_call=True,
        #     iac_path=request.iac_path,
        # )

    async def _load(self, request: _BaseIacRequest) -> Session:
        session = await DatabaseService.load_session(request.session_id)
        workspace: Workspace | None = await DatabaseService.get_workspace(
            request.session_id
        )
        if session is None:
            raise SessionTerminal(
                message=f"Session {request.session_id} not found.",
                error_code=404,
            )
        if session.user_id != request.user_id:
            raise SessionForbidden(
                message=f"Session {request.session_id} belongs to a different user.",
                error_code=400,
            )
        if workspace is None:
            raise SessionTerminal(
                message=f"Session {request.session_id} does not have a workspace",
                error_code=404,
            )
        if session.status == SessionStatus.FAILED:
            raise SessionTerminal(
                message=f"Session {request.session_id} is {session.status}.",
                error_code=409,
            )
        if not await DatabaseService.acquire_in_flight(request.session_id):
            raise SessionConflict(
                message=f"Session {request.session_id} already has a call in flight.",
                error_code=409,
            )
        return Session(
            id=session.uuid,
            user_id=session.user_id,
            repo_uri=workspace.uri,
            cloud=request.cloud,
            branch_name=workspace.branch,
            iac_path=workspace.root_path,
        )
        # return SessionContext(
        #     session_id=UUID(request.session_id),
        #     user_id=row.user_id,
        #     repo_uri=row.repo_uri,
        #     cloud=row.cloud_provider,
        #     environment=row.environment,
        #     branch_name=row.branch_name,
        #     history=list(row.history),
        #     is_first_call=False,
        #     iac_path=row.iac_path,
        # )

    async def release(self, session_id: UUID) -> None:
        _ = await DatabaseService.release_in_flight(str(session_id))
