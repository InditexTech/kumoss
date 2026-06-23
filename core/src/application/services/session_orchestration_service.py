# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from datetime import datetime
from uuid import UUID, uuid4

from src.application.dto import SessionContext
from src.application.exceptions import (
    SessionConflict,
    SessionForbidden,
    SessionTerminal,
)
from src.application.iac_requests import _BaseIacRequest
from src.domains.services.database_service import DatabaseService


class SessionOrchestrationService:
    """Resolves an incoming request into an in-flight SessionContext.

    Caller MUST pair `resolve(...)` with `release(session_id)` in a
    try/finally to clear the in_flight flag.
    """

    def _new_branch_name(self) -> str:
        ts = datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
        return f"Nebula/{ts}"

    async def resolve(
        self, request: _BaseIacRequest, operation_type: str = "generate"
    ) -> SessionContext:
        if request.repo_uri is not None:
            return await self._create(request, operation_type)
        return await self._load(request)

    async def _create(
        self, request: _BaseIacRequest, operation_type: str = "generate"
    ) -> SessionContext:
        sid = uuid4()
        branch = self._new_branch_name()
        _ = await DatabaseService.start_session(
            session_id=sid,
            user_id=request.user_id,
            repo_uri=request.repo_uri,
            cloud=request.cloud,
            environment=request.environment,
            branch_name=branch,
            operation_type=operation_type,
            iac_path=request.iac_path,
        )
        if not await DatabaseService.acquire_in_flight(str(sid)):
            # Should not happen on a fresh row, but defend anyway.
            raise SessionConflict("Failed to acquire in_flight lock on new session.")
        return SessionContext(
            session_id=sid,
            user_id=request.user_id,
            repo_uri=request.repo_uri,
            cloud=request.cloud,
            environment=request.environment,
            branch_name=branch,
            history=[],
            is_first_call=True,
            iac_path=request.iac_path,
        )

    async def _load(self, request: _BaseIacRequest) -> SessionContext:
        row = await DatabaseService.load_session(request.session_id)
        if row is None:
            raise SessionTerminal(f"Session {request.session_id} not found.")
        if row.user_id != request.user_id:
            raise SessionForbidden(
                f"Session {request.session_id} belongs to a different user."
            )
        if row.status != "active":
            raise SessionTerminal(f"Session {request.session_id} is {row.status}.")
        if not await DatabaseService.acquire_in_flight(request.session_id):
            raise SessionConflict(
                f"Session {request.session_id} already has a call in flight."
            )
        return SessionContext(
            session_id=UUID(request.session_id),
            user_id=row.user_id,
            repo_uri=row.repo_uri,
            cloud=row.cloud_provider,
            environment=row.environment,
            branch_name=row.branch_name,
            history=list(row.history),
            is_first_call=False,
            iac_path=row.iac_path,
        )

    async def release(self, session_id: UUID) -> None:
        await DatabaseService.release_in_flight(str(session_id))
