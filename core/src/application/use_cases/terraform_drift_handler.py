# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from uuid import UUID
from typing import Callable, Any
from collections.abc import Coroutine

from src.application.dto import SessionContext
from src.domains.entities.history import History
from src.domains.interfaces import ITerraformValidator
from src.domains.services import (
    ToolOrchestrationService,
    SessionService,
    TracerService,
    TemplateOrchestrationService,
    TerraformValidationService,
    TerraformTargetService,
)
from src.application.services import (
    ProjectSetupService,
    GeneratePayloadService,
    FilterRequestService,
    TerraformDriftService,
)
from src.domains.services.task_split_service import TaskSplitService
from src.infrastructure.telemetry.phoenix.phoenix_tracer import PhoenixTracer
from src.infrastructure.external.authz_service import AuthzServiceClient
from src.shared.config import system_config
from src.shared.constants import (
    SessionStatus,
    TracerProject,
    PromptsLibrary,
)
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging
from src.shared.utils.repo_uri import derive_project_name


class TerraformDriftHandler:
    def __init__(
        self,
        session_service: SessionService,
        validation_service: TerraformValidationService,
        template_service: TemplateOrchestrationService,
        filter_request_service: FilterRequestService,
        setup_service: ProjectSetupService,
        payload_svc: GeneratePayloadService,
        validator_provider: ITerraformValidator,
        tool_service: ToolOrchestrationService,
        target_service: TerraformTargetService,
        split_service: TaskSplitService,
        drift_service: TerraformDriftService,
        session_ctx: SessionContext,
    ):
        self.__validation_svc = validation_service
        self.__session_svc = session_service
        self.__template_svc = template_service
        self.__setup_svc = setup_service
        self.__payload_svc = payload_svc
        self.__filter_request_svc = filter_request_service
        self.__target_svc = target_service
        self.__drift_svc = drift_service
        self.__ctx = session_ctx

    async def handle(
        self, q: str, history: list[dict], is_partial: bool
    ) -> tuple[UUID, Callable[[], Coroutine[Any, Any, None]]]:
        ctx = self.__ctx
        hist = History(history)

        async def background_task():
            provider = TracerProject.PRO_TERRAFORM_DRIFT
            if system_config.environment == "development":
                provider = TracerProject.DEV_TERRAFORM_DRIFT
            elif system_config.environment == "staging":
                provider = TracerProject.PRE_TERRAFORM_DRIFT

            branch = await self.__setup_svc.setup_project()
            project = derive_project_name(ctx.repo_uri)

            try:
                _ = await AuthzServiceClient().check(
                    cloud=ctx.cloud,
                    project=project,
                    environment=ctx.environment,
                    user_id=ctx.user_id,
                )
                # portal_url no longer persisted on session row; pass-through only.
            except Exception as e:
                logging.warning(f"Could not resolve cloud portal URL: {e}")

            tracer_token = TracerService.set_current_tracer(
                tracer=PhoenixTracer(
                    provider_name=provider,
                    session_id=ctx.session_id,
                    user_id=ctx.user_id,
                    project=project,
                    environment=ctx.environment,
                    branch_name=branch,
                )
            )
            try:
                await self.__session_svc.update_status(
                    msg=q,
                    prompt=await self.__template_svc.render(
                        PromptsLibrary.TASK_ACKNOWLEDGE
                    ),
                    status=SessionStatus.FILTERING,
                )
                status, explanation = await self.__filter_request_svc.filter(q, hist)
                if not status:
                    await self.__payload_svc.generate(
                        response=explanation,
                        command=_LegacyCommandShim(ctx, q),
                        history=hist,
                        branch=branch,
                    )
                    return

                targets = []
                if is_partial:
                    targets = await self.__target_svc.generate(q, hist)

                validation = await self.__drift_svc.detect_and_resolve_drift(
                    branch=branch,
                    targets=targets,
                    history=hist,
                    max_iterations=system_config.orchestration.max_drift_reports,
                )

                await self.__payload_svc.generate_drift(
                    command=_LegacyCommandShim(ctx, q),
                    validation=validation,
                    branch=branch,
                )
            except ExceptionHandler as e:
                await self.__session_svc.update_status(
                    msg=e.message, status=SessionStatus.FAILED
                )
                raise
            finally:
                TracerService.reset_current_tracer(tracer_token)

        return ctx.session_id, background_task


class _LegacyCommandShim:
    """Adapter so GeneratePayloadService keeps its old `command.*` access pattern.

    GeneratePayloadService reads command.cloud, command.environment, command.q,
    command.user_id during payload assembly. We pass it a tiny shim instead of
    threading every field through a new signature.
    """

    def __init__(self, ctx, q: str):
        self.cloud = ctx.cloud
        self.environment = ctx.environment
        self.user_id = ctx.user_id
        self.q = q
        self.repository_id = ctx.repo_uri  # for any leftover access
