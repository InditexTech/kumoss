# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from datetime import datetime, timezone
from uuid import UUID, uuid4

from src.application.iac_requests import BaseIacRequest
from src.domains.entities import SessionContext
from src.domains.services.database_service import DatabaseService
from src.shared.constants import ReportType


class SessionOrchestrationService:
    """Resolves an incoming request into an in-flight SessionContext.

    Caller MUST pair `resolve(...)` with `release(session_id)` in a
    try/finally to clear the in_flight flag.
    """

    def __new_branch_name(self) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        return f"Nebula/{ts}"

    async def resolve(
        self, request: BaseIacRequest, operation_type: ReportType
    ) -> SessionContext:
        if request.session_id is None:
            return await self._create(request, operation_type)
        return await self._load(request, operation_type)

    async def _create(
        self, request: BaseIacRequest, operation_type: ReportType
    ) -> SessionContext:
        sid = uuid4()
        _ = await DatabaseService.create_session(
            session_id=sid,
            user_id=request.user_id,
            repo_uri=request.repo_uri,
            terraform_prv=request.terraform_providers,
            scope_id=request.scope_id,
            branch_name=self.__new_branch_name(),
            query=request.q,
            iac_path=request.iac_path,
        )
        sc = await DatabaseService.get_session_context(sid)
        sc.set_report_type(operation_type)
        return sc

    async def _load(
        self, request: BaseIacRequest, operation_type: ReportType
    ) -> SessionContext:
        sc = await DatabaseService.get_session_context(request.session_id)
        sc.set_report_type(operation_type)
        return sc

    async def acquire(self, session_id: UUID) -> None:
        _ = await DatabaseService.acquire_in_flight(session_id)

    async def release(self, session_id: UUID) -> None:
        _ = await DatabaseService.release_in_flight(session_id)
