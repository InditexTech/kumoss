# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException

from src.domains.services.tracer_service import tracer
from src.domains.services.database_service import DatabaseService
from src.domains.entities.session import SessionContext
from src.application.factory import ApplicationFactory
from src.application.iac_requests import (
    BaseIacRequest,
    GenerateRequest,
    DriftRequest,
    ApplyRequest,
    SessionRequest,
)
from src.application.services.session_orchestration_service import (
    SessionOrchestrationService,
)
from src.infrastructure.external.notification_service import NotificationServiceClient
from src.infrastructure.filesystem import WorkspaceService
from src.infrastructure.telemetry.phoenix.phoenix_tracer import PhoenixTracer
from src.shared.constants import OperationType, SessionStatus
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging

router = APIRouter(
    prefix="/iac",
    tags=["Infrastructure as Code"],
    responses={
        400: {
            "description": "Repository URI was rejected (unreachable or not allowed)."
        },
        404: {"description": "Iteration call referenced an unknown session."},
    },
)

_workspace = WorkspaceService()
_orchestration = SessionOrchestrationService()


async def _resolve_or_raise(
    request: BaseIacRequest | SessionRequest, operation: OperationType = None
) -> SessionContext:
    """Validate URI (first call) and resolve to a SessionContext entity.

    Session-only requests (e.g. apply) carry no ``repo_uri``: URI
    validation applies only to request models that define the field.
    """
    try:
        if isinstance(request, BaseIacRequest) and request.repo_uri is not None:
            await _workspace.validate_uri(request.repo_uri)
        return await _orchestration.resolve(request, operation)
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)


def _make_runner(
    ctx: SessionContext,
    build_handler: Callable[[SessionContext], Awaitable[Callable[[], Awaitable[Any]]]],
):
    """Build the full pipeline as a single background coroutine.

    `build_handler(call_dir)` is the use-case-specific bit: it constructs
    the right HandlerFactory and awaits its handler.handle(...) to return
    `(sse_id, run_handler)`. Everything else — workspace clone, push,
    history append, in_flight release — is the same regardless of use case.
    """

    async def runner():
        call_dir: Path | None = None
        try:
            await _orchestration.acquire(ctx.id)
        except ExceptionHandler as e:
            # never got the lock: the session is already running or is finished.
            logging.error(f"runner not started: {e.message} (session {ctx.id})")
            return
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
            call_dir = await _workspace.setup_call_dir(
                session_id=ctx.id,
                repo_uri=ctx.repo_uri,
                branch=ctx.branch_name,
            )
            ctx.set_call_dir(call_dir / ctx.iac_path)
            run_handler = await build_handler(ctx)
            await run_handler()
            last = await DatabaseService.get_last_status(ctx.id)
            if last.status is not SessionStatus.UNCOMPLETED:
                await DatabaseService.mark_completed(ctx.id, ctx.operation.name)
        except ExceptionHandler as e:
            msg = f"runner failed: {e.message}"
            logging.error(f"{msg} (session {ctx.id})")
            await DatabaseService.mark_failed(ctx.id, msg)
            await NotificationServiceClient.notify_exception_failure(ctx.id, msg)
            return
        finally:
            tracer.reset_current_tracer(tracer_token)
            _workspace.cleanup(call_dir)
            await _orchestration.release(ctx.id)

    return runner


@router.post(
    path="/generate",
    status_code=202,
    summary="Start an IaC generation session.",
)
async def generate_infrastructure(
    background_tasks: BackgroundTasks, request: GenerateRequest
) -> dict[str, str]:
    """Generates, validates, and prepares IaC based on a user query.
    Returns a session ID for tracking the background process.
    """
    ctx = await _resolve_or_raise(request, OperationType.GENERATE)

    async def build(context: SessionContext):
        handler = ApplicationFactory(session_ctx=context).get_terraform_crud_handler()
        return await handler.handle(request.q)

    background_tasks.add_task(_make_runner(ctx, build))
    return {"session_id": str(ctx.id)}


@router.post(
    path="/drift",
    status_code=202,
    summary="Start a drift detection and remediation session",
)
async def drift_detection_remediation(
    background_tasks: BackgroundTasks, request: DriftRequest
) -> dict[str, str]:
    """Performs Terraform drift detection and remediation.
    Returns a session ID for tracking the background process.
    """
    ctx = await _resolve_or_raise(request, OperationType.DRIFT)

    async def build(context: SessionContext):
        handler = ApplicationFactory(session_ctx=context).get_terraform_drift_handler()
        return await handler.handle(request.q, request.is_partial)

    background_tasks.add_task(_make_runner(ctx, build))
    return {"session_id": str(ctx.id)}


@router.post(
    path="/apply",
    status_code=202,
    summary="Start an apply session for prepared infrastructure changes.",
    responses={
        409: {
            "description": "Session is blocked by a failed compliance check, "
            + "or no reviewed plan is pinned for it."
        },
    },
)
async def apply_infrastructure(
    background_tasks: BackgroundTasks, request: ApplyRequest
) -> dict[str, str]:
    """Applies the plan pinned by the session's last successful generate or
    drift round — exactly the reviewed changes, with no re-plan at apply time.
    Returns a session ID for tracking the background process.
    """
    ctx = await _resolve_or_raise(request)
    if await DatabaseService.is_session_blocked(ctx.id):
        raise HTTPException(
            status_code=409,
            detail=f"Session {ctx.id} is blocked by a failed compliance check; apply is not allowed.",
        )

    async def build(context: SessionContext):
        handler = ApplicationFactory(session_ctx=context).get_terraform_apply_handler()
        return await handler.handle()

    background_tasks.add_task(_make_runner(ctx, build))
    return {"session_id": str(ctx.id)}
