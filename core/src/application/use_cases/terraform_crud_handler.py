# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Coroutine
from typing import Callable, Any

from src.application.services.filter_request_service import FilterRequestService
from src.application.services.generate_payload_service import GeneratePayloadService
from src.application.services.terraform_drift_service import TerraformDriftService
from src.domains.entities.session import SessionContext
from src.domains.services import (
    SessionService,
    TracerService,
    TemplateOrchestrationService,
    TerraformValidationService,
    TerraformTargetService,
)
from src.infrastructure.external.authz_service import AuthzServiceClient
from src.infrastructure.telemetry.phoenix.phoenix_tracer import PhoenixTracer
from src.shared.config import system_config
from src.shared.constants import SessionStatus, TracerProject, PromptsLibrary
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging
from src.shared.utils.repo_uri import derive_project_name


class TerraformCRUDHandler:
    def __init__(
        self,
        session_service: SessionService,
        validation_service: TerraformValidationService,
        template_service: TemplateOrchestrationService,
        filter_request_service: FilterRequestService,
        payload_svc: GeneratePayloadService,
        target_svc: TerraformTargetService,
        drift_svc: TerraformDriftService,
        session_ctx: SessionContext,
    ):
        self.__validation_svc = validation_service
        self.__session_svc = session_service
        self.__template_svc = template_service
        self.__payload_svc = payload_svc
        self.__filter_request_svc = filter_request_service
        self.__target_svc = target_svc
        self.__drift_svc = drift_svc
        self.__ctx = session_ctx

    async def handle(self, q: str) -> Callable[[], Coroutine[Any, Any, None]]:
        ctx = self.__ctx
        hist = ctx.history.deepcopy()

        async def background_task():
            provider = TracerProject.PRO_TERRAFORM_DAY2
            if system_config.environment == "development":
                provider = TracerProject.DEV_TERRAFORM_DAY2
            elif system_config.environment == "staging":
                provider = TracerProject.PRE_TERRAFORM_DAY2

            project = derive_project_name(ctx.repo_uri)

            _ = await AuthzServiceClient().check(
                cloud=ctx.cloud,
                project=project,
                user_id=ctx.user_id,
            )

            tracer_token = TracerService.set_current_tracer(
                tracer=PhoenixTracer(
                    provider_name=provider,
                    session_id=ctx.id,
                    user_id=ctx.user_id,
                    project=project,
                    branch_name=ctx.branch_name,
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
                        command="TODO",
                        history=hist,
                        branch=ctx.branch_name,
                    )
                    return

                predictive_targets = await self.__target_svc.generate_predictive(
                    query=q, history=hist, include_forbidden_actions=True
                )
                if predictive_targets:
                    drift_result = await self.__drift_svc.detect_and_resolve_drift(
                        branch=ctx.branch_name,
                        targets=predictive_targets,
                        history=hist,
                        max_iterations=2,
                    )
                    if drift_result.validation:
                        logging.warning(
                            "Drift pre-check completed, resources are synchronized"
                        )
                    else:
                        logging.warning("Drift resolution completed but issues remain")

                validation_result = await self.__validation_svc.generate_and_validate(
                    query=q, history=hist, include_forbidden_actions=True
                )
                await self.__payload_svc.generate(
                    response="",
                    command="TODO",
                    history=hist,
                    branch=ctx.branch_name,
                    validation=validation_result,
                )
            except ExceptionHandler as e:
                await self.__session_svc.update_status(
                    msg=e.message, status=SessionStatus.FAILED
                )
                raise
            finally:
                TracerService.reset_current_tracer(tracer_token)

        return background_task
