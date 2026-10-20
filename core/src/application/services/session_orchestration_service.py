# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from datetime import datetime, timezone
from uuid import UUID, uuid4

from src.application.iac_requests import (
    BaseIacRequest,
    DriftRequest,
    GenerateRequest,
    SessionRequest,
)
from src.domains.entities import SessionContext
from src.domains.services.database_service import DatabaseService
from src.shared.constants import OperationType


class SessionOrchestrationService:
    """Resolves an incoming request into a SessionContext; creates the
    session on a first call."""

    def __new_branch_name(self, session_id: UUID) -> str:
        # The session id suffix keeps sessions created in the same second
        # (e.g. schedules sharing a cron) off each other's branch.
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        return f"Kumoss/{ts}_{session_id.hex[:8]}"

    async def resolve(
        self,
        request: BaseIacRequest | SessionRequest,
        operation: OperationType | None = None,
        user_pk: int | None = None,
    ) -> SessionContext:
        if (
            isinstance(request, BaseIacRequest)
            and request.session_id is None
            and operation is not None
            and user_pk is not None
        ):
            return await self._create(request, operation, user_pk)
        return await self._load(request)

    async def _create(
        self,
        request: GenerateRequest | DriftRequest,
        operation: OperationType,
        user_pk: int,
    ) -> SessionContext:
        sid = uuid4()
        _ = await DatabaseService.create_session(
            session_id=sid,
            user_pk=user_pk,
            operation=operation,
            repo_uri=request.repo_uri,
            terraform_prv=request.terraform_providers,
            scope_id=request.scope_id,
            branch_name=self.__new_branch_name(sid),
            query=request.q,
            iac_path=request.iac_path,
        )
        return await DatabaseService.get_session_context(sid)

    async def _load(self, request: BaseIacRequest | SessionRequest) -> SessionContext:
        return await DatabaseService.get_session_context(request.session_id)
