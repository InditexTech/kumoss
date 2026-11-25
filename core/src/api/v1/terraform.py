# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from src.api.authz import authorize_providers
from src.api.deps import (
    assert_session_access,
    get_validated_claims,
    require_operation_role,
)
from src.application.exceptions import RequestFilterException
from src.application.factory import ApplicationFactory
from src.application.iac_requests import (
    ApplyRequest,
    BaseIacRequest,
    DriftRequest,
    GenerateRequest,
    ImportRequest,
    ManifestAnswers,
    SessionRequest,
)
from src.application.services.session_orchestration_service import (
    SessionOrchestrationService,
)
from src.clients.authz.models.action_name import ActionName
from src.domains.entities import SessionContext, User
from src.domains.services.manifest_service import Authorize
from src.domains.value_objects.provider_scope import ProviderScope
from src.domains.services.database_service import DatabaseService
from src.domains.services.tracer_service import tracer
from src.domains.value_objects.token_claims import TokenClaims
from src.infrastructure.external.notification_service import NotificationServiceClient
from src.infrastructure.filesystem import WorkspaceService
from src.infrastructure.telemetry.langfuse_tracer import LangfuseTracer
from src.shared.constants import (
    OperationRole,
    OperationType,
    SessionStatus,
)
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
    request: BaseIacRequest | SessionRequest,
    user: User,
    claims: TokenClaims,
    operation: OperationType,
) -> SessionContext:
    """Validate URI, authorize via PDP, and resolve to a SessionContext.

    First-call (has ``repo_uri``): URI validation → session creation, so
    an unreachable repository leaves no session behind. The providers and
    scopes to authorize come from the root module's manifest, so authz runs
    in the session itself, before its setup saves anything (see
    ``_Inputs``). Iteration / session-only (has ``session_id``): ownership
    check → session load → operation check → URI validation → authz on
    every scope recorded at the session's setup.
    """

    try:
        if isinstance(request, BaseIacRequest) and request.session_id is None:
            await _workspace.validate_uri(request.repo_uri)
            return await _orchestration.resolve(request, operation, user.id)

        await assert_session_access(user, request.session_id, write=True)
        ctx = await _orchestration.resolve(request, operation, user.id)
        if operation is not OperationType.APPLY and ctx.operation is not operation:
            raise HTTPException(
                status_code=409,
                detail="The requested operation does not match the session operation.",
            )
        await _check_access(
            claims,
            operation,
            providers=ctx.providers,
            repo_uri=ctx.repo_uri,
            root_module_path=ctx.root_module_path,
        )
        return ctx
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)


async def _check_access(
    claims: TokenClaims,
    operation: OperationType,
    *,
    providers: tuple[ProviderScope, ...],
    repo_uri: str,
    root_module_path: str | None,
) -> None:
    """Validate the repository, then authorize every scope of the session."""
    await _workspace.validate_uri(repo_uri)
    await authorize_providers(
        claims,
        ActionName(operation.value),
        providers=providers,
        repo_uri=repo_uri,
        root_module_path=root_module_path,
    )


@dataclass(frozen=True)
class _Inputs:
    """How a call puts the root module's inputs in place (see SessionInputsService).

    A first call also authorizes ``action`` for ``claims`` on the providers
    and scopes its setup finds, before anything is saved.
    """

    first_call: bool
    claims: TokenClaims
    action: ActionName
    answers: ManifestAnswers | None = None

    @classmethod
    def of(
        cls, request: BaseIacRequest, claims: TokenClaims, operation: OperationType
    ) -> "_Inputs":
        return cls(
            first_call=request.session_id is None,
            claims=claims,
            action=ActionName(operation.value),
            answers=request.manifest,
        )

    def authorizer(self, ctx: SessionContext) -> Authorize:
        async def authorize_setup(providers: tuple[ProviderScope, ...]) -> None:
            try:
                await authorize_providers(
                    self.claims,
                    self.action,
                    providers=providers,
                    repo_uri=ctx.repo_uri,
                    root_module_path=ctx.root_module_path,
                )
            except HTTPException as e:
                # The runner reports ExceptionHandler errors on the session.
                raise ExceptionHandler(str(e.detail), e.status_code) from e

        return authorize_setup


async def _claim(ctx: SessionContext) -> None:
    """Claim the session's in-flight flag before accepting the call.

    A session that is already running, or is finished, is refused here
    with a 409 rather than accepted and then silently dropped by the
    runner. Call it right before scheduling the runner, which releases it.
    """
    try:
        await _orchestration.acquire(ctx.id)
    except ExceptionHandler as e:
        raise HTTPException(status_code=e.error_code, detail=e.message)


def _make_runner(
    ctx: SessionContext,
    build_handler: Callable[[SessionContext], Awaitable[Callable[[], Awaitable[Any]]]],
    inputs: _Inputs | None = None,
):
    """Build the full pipeline as a single background coroutine.

    `build_handler(call_dir)` is the use-case-specific bit: it constructs
    the right HandlerFactory and awaits its handler.handle(...) to return
    `(sse_id, run_handler)`. Everything else — workspace clone, push,
    history append, in_flight release — is the same regardless of use case.

    `inputs`, when given, puts the root module's input variables in place
    before the handler is built; None (apply) runs on a pinned plan that
    already carries them.
    """

    async def runner():
        # The endpoint claimed the session's in-flight flag (see _claim);
        # the runner owns it from here and releases it when done.
        call_dir: Path | None = None
        tracer_token = tracer.set_current_tracer(
            tracer=LangfuseTracer(
                session_id=ctx.id,
                user_id=ctx.user_id,
                branch_name=ctx.branch_name,
                providers=ctx.provider_types,
                repo_uri=ctx.repo_uri,
                root_module_path=ctx.root_module_path,
                operation=ctx.operation,
            )
        )
        try:
            call_dir = await _workspace.setup_call_dir(
                session_id=ctx.id,
                repo_uri=ctx.repo_uri,
                branch=ctx.branch_name,
            )
            ctx.set_call_dir(_workspace.root_module_dir(call_dir, ctx.root_module_path))
            if inputs is not None:
                await ApplicationFactory.get_session_inputs_service(
                    ctx.repo_uri, call_dir
                ).prepare(
                    ctx,
                    first_call=inputs.first_call,
                    answers=inputs.answers,
                    authorize=inputs.authorizer(ctx) if inputs.first_call else None,
                )
            run_handler = await build_handler(ctx)
            await run_handler()
            last = await DatabaseService.get_last_status(ctx.id)
            if last.status is not SessionStatus.UNCOMPLETED:
                await DatabaseService.mark_completed(ctx.id, ctx.operation.name)
        except RequestFilterException:
            await DatabaseService.mark_uncompleted(
                ctx.id, ctx.chat_history.get_last_turn().assistant
            )
        except ExceptionHandler as e:
            msg = f"runner failed: {e.message}"
            logging.error(f"{msg} (session {ctx.id})")
            await DatabaseService.mark_failed(ctx.id, msg)
            await NotificationServiceClient.notify_exception_failure(
                ctx.id, ctx.user_id, msg
            )
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
    background_tasks: BackgroundTasks,
    request: GenerateRequest,
    user: Annotated[User, Depends(require_operation_role(OperationRole.DEVELOPER))],
    claims: Annotated[TokenClaims, Depends(get_validated_claims)],
) -> dict[str, str]:
    """Generates, validates, and prepares IaC based on a user query.
    Returns a session ID for tracking the background process.
    """
    ctx = await _resolve_or_raise(request, user, claims, OperationType.GENERATE)

    async def build(context: SessionContext):
        handler = ApplicationFactory(session_ctx=context).get_terraform_crud_handler()
        return await handler.handle(request.q)

    await _claim(ctx)
    background_tasks.add_task(
        _make_runner(ctx, build, _Inputs.of(request, claims, OperationType.GENERATE))
    )
    return {"session_id": str(ctx.id)}


@router.post(
    path="/drift",
    status_code=202,
    summary="Start a drift detection and remediation session",
)
async def drift_detection_remediation(
    background_tasks: BackgroundTasks,
    request: DriftRequest,
    user: Annotated[User, Depends(require_operation_role(OperationRole.DEVOPS))],
    claims: Annotated[TokenClaims, Depends(get_validated_claims)],
) -> dict[str, str]:
    """Performs Terraform drift detection and remediation.
    Returns a session ID for tracking the background process.
    """
    ctx = await _resolve_or_raise(request, user, claims, OperationType.DRIFT)

    async def build(context: SessionContext):
        handler = ApplicationFactory(session_ctx=context).get_terraform_drift_handler()
        return await handler.handle(request.q, request.is_partial)

    await _claim(ctx)
    background_tasks.add_task(
        _make_runner(ctx, build, _Inputs.of(request, claims, OperationType.DRIFT))
    )
    return {"session_id": str(ctx.id)}


@router.post(
    path="/apply",
    status_code=202,
    summary="Start an apply session for prepared infrastructure changes.",
    responses={
        409: {"description": "Session is blocked."},
    },
)
async def apply_infrastructure(
    background_tasks: BackgroundTasks,
    request: ApplyRequest,
    user: Annotated[User, Depends(require_operation_role(OperationRole.DEVELOPER))],
    claims: Annotated[TokenClaims, Depends(get_validated_claims)],
) -> dict[str, str]:
    """Applies the plan pinned by the session's last successful generate or
    drift round — exactly the reviewed changes, with no re-plan at apply time.
    Returns a session ID for tracking the background process.
    """
    ctx = await _resolve_or_raise(request, user, claims, OperationType.APPLY)
    if await DatabaseService.is_session_blocked(ctx.id):
        raise HTTPException(
            status_code=409,
            detail=f"Session {ctx.id} is blocked; apply is not allowed.",
        )

    async def build(context: SessionContext):
        handler = ApplicationFactory(session_ctx=context).get_terraform_apply_handler()
        return await handler.handle()

    await _claim(ctx)
    background_tasks.add_task(_make_runner(ctx, build))
    return {"session_id": str(ctx.id)}


@router.post(
    path="/import",
    status_code=202,
    summary="Start an IaC import session.",
)
async def import_infrastructure(
    background_tasks: BackgroundTasks,
    request: ImportRequest,
    user: Annotated[User, Depends(require_operation_role(OperationRole.DEVELOPER))],
    claims: Annotated[TokenClaims, Depends(get_validated_claims)],
) -> dict[str, str]:
    """Imports, validates, and prepares IaC based on a user query.
    Returns a session ID for tracking the background process.
    """
    ctx = await _resolve_or_raise(request, user, claims, OperationType.IMPORT)

    async def build(context: SessionContext):
        handler = ApplicationFactory(session_ctx=context).get_terraform_import_handler()
        return await handler.handle(request.q, request.is_partial)

    await _claim(ctx)
    background_tasks.add_task(
        _make_runner(ctx, build, _Inputs.of(request, claims, OperationType.IMPORT))
    )
    return {"session_id": str(ctx.id)}
