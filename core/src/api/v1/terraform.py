# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException

from src.domains.services.database_service import DatabaseService
from src.domains.entities.session import SessionContext
from src.application.factory import ApplicationFactory
from src.application.iac_requests import (
    BaseIacRequest,
    GenerateRequest,
    DriftRequest,
    ApplyRequest,
)
from src.application.services.session_orchestration_service import (
    SessionOrchestrationService,
)
from src.infrastructure.filesystem import WorkspaceService
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging

router = APIRouter(prefix="/iac", tags=["Infrastructure as Code"])

_workspace = WorkspaceService()
_orchestration = SessionOrchestrationService()


async def _resolve_or_raise(request: BaseIacRequest) -> SessionContext:
    """Validate URI (first call) and resolve to a SessionContext entity."""
    try:
        if request.repo_uri is not None:
            await _workspace.validate_uri(request.repo_uri)
        return await _orchestration.resolve(request)
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
        call_id = uuid4()
        call_dir: Path | None = None
        try:
            await _orchestration.acquire(ctx.id)
            call_dir = await _workspace.setup_call_dir(
                session_id=ctx.id,
                call_id=call_id,
                repo_uri=ctx.repo_uri,
                branch=ctx.branch_name,
            )
            ctx.set_call_dir(call_dir / ctx.iac_path)
            await _workspace.push(call_dir=call_dir, branch=ctx.branch_name)
            run_handler = await build_handler(ctx)
            await run_handler()
        except ExceptionHandler as e:
            msg = f"runner failed: {e.message}"
            logging.error(f"{msg} (session {ctx.id})")
            await DatabaseService.mark_failed(str(ctx.id), msg)
            return
        finally:
            _workspace.cleanup(call_dir)
            await _orchestration.release(ctx.id)

    return runner


@router.post("/generate", status_code=202)
async def generate_infrastructure(
    background_tasks: BackgroundTasks, request: GenerateRequest
) -> dict[str, str]:
    """Generates, validates, and prepares IaC based on a user query.
    Returns a session ID for tracking the background process.
    """
    ctx = await _resolve_or_raise(request)

    async def build(context: SessionContext):
        handler = ApplicationFactory(session_ctx=context).get_terraform_crud_handler()
        return await handler.handle(request.q)

    background_tasks.add_task(_make_runner(ctx, build))
    return {"session_id": str(ctx.id)}


@router.post("/drift", status_code=202)
async def drift_detection_remediation(
    background_tasks: BackgroundTasks, request: DriftRequest
) -> dict[str, str]:
    """Performs Terraform drift detection and remediation.
    Returns a session ID for tracking the background process.
    """
    ctx = await _resolve_or_raise(request)

    async def build(context: SessionContext):
        handler = ApplicationFactory(session_ctx=context).get_terraform_drift_handler()
        return await handler.handle(request.q, request.is_partial)

    background_tasks.add_task(_make_runner(ctx, build))
    return {"session_id": str(ctx.id)}


@router.post("/apply", status_code=202)
async def apply_infrastructure(
    background_tasks: BackgroundTasks, request: ApplyRequest
) -> dict[str, str]:
    """Applies the infrastructure changes for a given project and environment.
    Returns a session ID for tracking the background process.
    """
    ctx = await _resolve_or_raise(request)

    async def build(context: SessionContext):
        handler = ApplicationFactory(session_ctx=context).get_terraform_apply_handler()
        return await handler.handle(request.q, request.terraform_targets)

    background_tasks.add_task(_make_runner(ctx, build))
    return {"session_id": str(ctx.id)}
