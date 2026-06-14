# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4, UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException

from src.application.factory import HandlerFactory
from src.application.iac_requests import (
    GenerateRequest,
    DriftRequest,
    ApplyRequest,
)
from src.application.dto import SessionContext
from src.application.exceptions import (
    SessionConflict,
    SessionForbidden,
    SessionTerminal,
)
from src.application.services.session_orchestration_service import (
    SessionOrchestrationService,
)
from src.infrastructure.filesystem.workspace import WorkspaceService, InvalidRepoURI
from src.domains.services.database_service import DatabaseService
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging

router = APIRouter(prefix="/iac", tags=["Infrastructure as Code"])

_workspace = WorkspaceService()
_orchestration = SessionOrchestrationService()


async def _resolve_or_raise(
    request, operation_type: str = "generate"
) -> SessionContext:
    """Validate URI (first call) and resolve to a SessionContext."""
    if request.repo_uri is not None:
        try:
            await _workspace.validate_uri(request.repo_uri)
        except InvalidRepoURI as e:
            raise HTTPException(status_code=400, detail=str(e))
    try:
        return await _orchestration.resolve(request, operation_type)
    except SessionForbidden as e:
        raise HTTPException(status_code=403, detail=str(e))
    except (SessionConflict, SessionTerminal) as e:
        raise HTTPException(status_code=409, detail=str(e))


def _make_runner(
    ctx: SessionContext,
    q: str,
    build_handler: Callable[
        [Path], Awaitable[tuple[UUID, Callable[[], Awaitable[Any]]]]
    ],
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
            call_dir = await _workspace.setup_call_dir(
                session_id=ctx.session_id,
                call_id=call_id,
                repo_uri=ctx.repo_uri,
                branch=ctx.branch_name,
                create_branch=ctx.is_first_call,
            )
        except Exception as e:
            msg = f"Workspace setup failed: {e}"
            logging.error(f"{msg} (session {ctx.session_id})")
            await DatabaseService.mark_failed(str(ctx.session_id), msg)
            await _orchestration.release(ctx.session_id)
            return

        try:
            _sse_id, run_handler = await build_handler(call_dir)
        except ExceptionHandler as e:
            msg = f"Handler setup failed: {e.message}"
            logging.error(f"{msg} (session {ctx.session_id})")
            await DatabaseService.mark_failed(str(ctx.session_id), msg)
            _workspace.cleanup(call_dir)
            await _orchestration.release(ctx.session_id)
            return
        except Exception as e:
            msg = f"Unexpected error preparing handler: {e}"
            logging.error(f"{msg} (session {ctx.session_id})")
            await DatabaseService.mark_failed(str(ctx.session_id), msg)
            _workspace.cleanup(call_dir)
            await _orchestration.release(ctx.session_id)
            return

        try:
            await run_handler()
            try:
                await _workspace.push_and_cleanup(
                    call_dir=call_dir, branch=ctx.branch_name
                )
            except Exception as e:
                msg = f"Push failed: {e}"
                logging.error(f"{msg} (session {ctx.session_id})")
                await DatabaseService.mark_failed(str(ctx.session_id), msg)
                _workspace.cleanup(call_dir)
                return
            await DatabaseService.append_history(
                str(ctx.session_id), {"user": q, "assistant": ""}
            )
        except Exception as e:
            logging.error(f"Use-case failed for session {ctx.session_id}: {e}")
            await DatabaseService.mark_failed(str(ctx.session_id), str(e))
            _workspace.cleanup(call_dir)
        finally:
            await _orchestration.release(ctx.session_id)

    return runner


@router.post("/generate", status_code=202)
async def generate_infrastructure(
    background_tasks: BackgroundTasks, request: GenerateRequest
) -> dict[str, str]:
    """Generates, validates, and prepares IaC based on a user query.
    Returns a session ID for tracking the background process.
    """
    ctx = await _resolve_or_raise(request, "generate")

    async def build(call_dir):
        handler = HandlerFactory(
            session_ctx=ctx, call_dir=call_dir, q=request.q
        ).get_terraform_crud_handler()
        return await handler.handle(request.q, ctx.history)

    background_tasks.add_task(_make_runner(ctx, request.q, build))
    return {"session_id": str(ctx.session_id)}


@router.post("/drift", status_code=202)
async def drift_detection_remediation(
    background_tasks: BackgroundTasks, request: DriftRequest
) -> dict[str, str]:
    """Performs Terraform drift detection and remediation.
    Returns a session ID for tracking the background process.
    """
    ctx = await _resolve_or_raise(request, "drift")

    async def build(call_dir):
        handler = HandlerFactory(
            session_ctx=ctx, call_dir=call_dir, q=request.q
        ).get_terraform_drift_handler()
        return await handler.handle(request.q, ctx.history, request.is_partial)

    background_tasks.add_task(_make_runner(ctx, request.q, build))
    return {"session_id": str(ctx.session_id)}


@router.post("/apply", status_code=202)
async def apply_infrastructure(
    background_tasks: BackgroundTasks, request: ApplyRequest
) -> dict[str, str]:
    """Applies the infrastructure changes for a given project and environment.
    Returns a session ID for tracking the background process.
    """
    ctx = await _resolve_or_raise(request, "apply")

    async def build(call_dir):
        handler = HandlerFactory(
            session_ctx=ctx,
            call_dir=call_dir,
            q=request.q,
            terraform_targets=request.terraform_targets,
        ).get_terraform_apply_handler()
        return await handler.handle(request.q, request.terraform_targets)

    background_tasks.add_task(_make_runner(ctx, request.q, build))
    return {"session_id": str(ctx.session_id)}
