# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Single entry point that turns a terraform request into a queued operation.

Both the ``/iac`` controllers and the cron materializer submit through
here, so every operation — interactive or scheduled — resolves its session
the same way and runs through the same Postgres queue and executor.
"""

from typing import Any, final

from pydantic import ValidationError

from src.application.iac_requests import (
    ApplyRequest,
    BaseIacRequest,
    DriftRequest,
    GenerateRequest,
    ImportRequest,
)
from src.application.services.session_orchestration_service import (
    SessionOrchestrationService,
)
from src.domains.entities import SessionContext
from src.domains.services.database_service import DatabaseService
from src.domains.services.operation_queue_service import OperationQueueService
from src.infrastructure.database.models import Operation
from src.shared.constants import OperationRole, OperationType
from src.shared.exceptions import ExceptionHandler

IacRequest = GenerateRequest | DriftRequest | ImportRequest | ApplyRequest

# Minimum operation role per kind, shared by the /iac routes, schedule
# creation and the cron materializer (which re-checks at fire time).
OPERATION_MIN_ROLE: dict[OperationType, OperationRole] = {
    OperationType.GENERATE: OperationRole.DEVELOPER,
    OperationType.DRIFT: OperationRole.DEVOPS,
    OperationType.IMPORT: OperationRole.DEVELOPER,
    OperationType.APPLY: OperationRole.DEVELOPER,
}

# Kinds a cron schedule may fire. Generate needs a human in the loop and
# apply needs an existing, reviewed session, so neither is schedulable.
_SCHEDULE_REQUESTS: dict[OperationType, type[DriftRequest | ImportRequest]] = {
    OperationType.DRIFT: DriftRequest,
    OperationType.IMPORT: ImportRequest,
}
SCHEDULABLE_KINDS = frozenset(_SCHEDULE_REQUESTS)


def schedule_request(
    kind: OperationType, params: dict[str, Any]
) -> DriftRequest | ImportRequest:
    """Validate schedule params as the first-call request the cron will submit."""
    model = _SCHEDULE_REQUESTS.get(kind)
    if model is None:
        raise ExceptionHandler(
            message=f"Operation kind '{kind.value}' cannot be scheduled.",
            error_code=422,
        )
    try:
        request = model.model_validate(params)
    except ValidationError as e:
        raise ExceptionHandler(
            message=f"Invalid schedule params: {e.errors(include_url=False)}",
            error_code=422,
        )
    if request.session_id is not None:
        raise ExceptionHandler(
            message="Schedule params must describe a first call (repo_uri), not a session_id.",
            error_code=422,
        )
    return request


@final
class OperationSubmissionService:
    def __init__(
        self,
        queue: OperationQueueService,
        orchestration: SessionOrchestrationService | None = None,
    ) -> None:
        self._queue = queue
        self._orchestration = orchestration or SessionOrchestrationService()

    async def submit(
        self,
        request: IacRequest,
        kind: OperationType,
        user_pk: int,
        schedule_id: int | None = None,
    ) -> tuple[SessionContext, Operation]:
        """Resolve (or create) the session and enqueue the operation on it."""
        if isinstance(request, BaseIacRequest):
            ctx = await self._orchestration.resolve(request, kind, user_pk)
        else:
            ctx = await self._orchestration.resolve(request)
            if kind is OperationType.APPLY and await DatabaseService.is_session_blocked(
                ctx.id
            ):
                raise ExceptionHandler(
                    message=f"Session {ctx.id} is blocked; apply is not allowed.",
                    error_code=409,
                )
        op = await self._queue.enqueue(
            session_id=ctx.id,
            kind=kind,
            params=request.model_dump(mode="json", exclude_none=True),
            schedule_id=schedule_id,
        )
        return ctx, op
