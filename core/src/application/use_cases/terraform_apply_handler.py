# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Coroutine
from typing import Callable, Any

from src.domains.entities import SessionContext
from src.domains.services import (
    TemplateOrchestrationService,
    TracerService,
    SessionService,
)
from src.infrastructure.telemetry.phoenix.phoenix_tracer import PhoenixTracer
from src.shared.constants import SessionStatus, TracerProject, PromptsLibrary
from src.shared.config import system_config
from src.shared.exceptions import ExceptionHandler
from src.shared.utils.repo_uri import derive_project_name


class TerraformApplyHandler:
    def __init__(
        self,
        apply_service,
        session_service: SessionService,
        template_service: TemplateOrchestrationService,
        session_ctx: SessionContext,
    ):
        self.__apply_svc = apply_service
        self.__session_svc = session_service
        self.__template_svc = template_service
        self.__ctx = session_ctx

    async def handle(
        self, q: str, terraform_targets: list[str]
    ) -> Callable[[], Coroutine[Any, Any, None]]:
        ctx = self.__ctx

        async def task_background():
            provider = TracerProject.PRO_TERRAFORM_DAY2
            if system_config.environment == "development":
                provider = TracerProject.DEV_TERRAFORM_DAY2
            elif system_config.environment == "staging":
                provider = TracerProject.PRE_TERRAFORM_DAY2

            project = derive_project_name(ctx.repo_uri)

            tracer_token = TracerService.set_current_tracer(
                tracer=PhoenixTracer(
                    provider_name=provider,
                    session_id=ctx.session_id,
                    user_id=ctx.user_id,
                    project=project,
                    environment=ctx.environment,
                    branch_name=ctx.branch_name,
                )
            )
            try:
                await self.__session_svc.update_status(
                    msg="The code has been generated and now Terraform Apply is "
                    + "running in the background.",
                    prompt=await self.__template_svc.render(
                        PromptsLibrary.STATUS_UPDATE
                    ),
                    status=SessionStatus.STARTED,
                )
                apply_results = await self.__apply_svc.apply(terraform_targets)
                if not apply_results:
                    raise ExceptionHandler(
                        message="I couldn't apply the infrastructure. Please, contact with the Data DevOps team",
                        error_code=500,
                    )
                await self.__payload_svc.generate_apply(
                    response=apply_results.portal_url,
                    command=_LegacyCommandShim(ctx, q),
                    validation=True if apply_results.portal_url else False,
                    run_id=apply_results.run_id,
                    apply_output=apply_results.apply_output,
                )
            except ExceptionHandler as e:
                await self.__session_svc.update_status(
                    msg=e.message, status=SessionStatus.FAILED
                )
                raise
            finally:
                TracerService.reset_current_tracer(tracer_token)

        return task_background


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
