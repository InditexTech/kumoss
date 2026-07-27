# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Coroutine
from typing import Callable, Any
from uuid import UUID

from src.application.dto import SessionContext
from src.clients.notifications_factory import get_notifications_client
from src.clients.notifications.api.notify import notify as notify_api
from src.clients.notifications.models.notification_request import NotificationRequest
from src.clients.notifications.models.notification_request_severity import (
    NotificationRequestSeverity,
)
from src.domains.dto import ComplianceCheckReport, ComplianceContextDTO
from src.domains.entities.history import History
from src.domains.services import (
    ComplianceCheckService,
    SessionService,
    TemplateOrchestrationService,
    TracerService,
)
from src.domains.services.database_service import DatabaseService
from src.infrastructure.telemetry.phoenix.phoenix_tracer import PhoenixTracer
from src.infrastructure.templates._fetcher import remote_fetcher
from src.shared.config import system_config
from src.shared.constants import SessionStatus, TracerProviderEnum, PromptsLibrary
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging
from src.shared.utils.repo_uri import derive_project_name


class ComplianceCheckHandler:
    def __init__(
        self,
        compliance_service: ComplianceCheckService,
        session_service: SessionService,
        template_service: TemplateOrchestrationService,
        session_ctx: SessionContext,
    ):
        self.__compliance_svc = compliance_service
        self.__session_svc = session_service
        self.__template_svc = template_service
        self.__ctx = session_ctx

    async def handle(
        self,
        mode: str,
        history: list[dict],
        phoenix_prompt_name: str | None = None,
    ) -> tuple[UUID, Callable[[], Coroutine[Any, Any, None]]]:
        ctx = self.__ctx
        self.__session_svc.create_session(ctx.session_id)
        hist = History(history)

        async def background_task():
            provider = TracerProviderEnum.PRO_TERRAFORM_DAY2
            if system_config.environment == "development":
                provider = TracerProviderEnum.DEV_TERRAFORM_DAY2
            elif system_config.environment == "staging":
                provider = TracerProviderEnum.PRE_TERRAFORM_DAY2

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
                    msg="Running compliance check",
                    prompt=await self.__template_svc.render(
                        PromptsLibrary.TASK_ACKNOWLEDGE
                    ),
                    status=SessionStatus.VALIDATING,
                )

                rules = await self.__compose_rules(mode, phoenix_prompt_name)
                plan_report = await self.__load_plan_report(ctx.session_id)

                compliance_ctx = ComplianceContextDTO(
                    output_under_check=plan_report,
                    rules=rules,
                    history=hist.serialize(),
                )

                report: ComplianceCheckReport = await self.__compliance_svc.check(
                    context=compliance_ctx,
                )

                if not report.passed:
                    await DatabaseService.set_apply_allowed(
                        str(ctx.session_id), False
                    )
                    await self.__notify_failure(ctx, report)

                await self.__session_svc.set_payload(
                    query=f"compliance-check:{mode}",
                    response=report.summary,
                    history=hist,
                    validation=report.passed,
                    project=project,
                    environment=ctx.environment,
                    cloud=ctx.cloud,
                    branch=ctx.branch_name,
                    compliance_report=report,
                    apply_allowed=report.passed,
                )
                await self.__session_svc.update_status(
                    msg=report.summary,
                    status=SessionStatus.COMPLETED
                    if report.passed
                    else SessionStatus.FAILED,
                )
            except ExceptionHandler as e:
                await self.__session_svc.update_status(
                    msg=e.message, status=SessionStatus.FAILED
                )
                raise
            finally:
                TracerService.reset_current_tracer(tracer_token)

        return ctx.session_id, background_task

    @staticmethod
    async def __notify_failure(
        ctx: SessionContext, report: ComplianceCheckReport
    ) -> None:
        client = get_notifications_client()
        if client is None:
            return
        try:
            await notify_api.asyncio(
                client=client,
                body=NotificationRequest(
                    kind="iac.compliance.check_failed",
                    severity=NotificationRequestSeverity.ERROR,
                    subject=f"Compliance check failed – session {ctx.session_id}",
                    body=report.summary,
                ),
            )
        except Exception:
            logging.warning(
                f"Failed to send compliance-failure notification for session {ctx.session_id}"
            )

    @staticmethod
    async def __load_plan_report(session_id: UUID) -> str | None:
        row = await DatabaseService.load_session(str(session_id))
        if row is None or row.last_payload is None:
            return None
        return row.last_payload.get("terraform_plan")

    async def __compose_rules(
        self, mode: str, phoenix_prompt_name: str | None
    ) -> str | None:
        if mode == "plan_vs_custom":
            return await remote_fetcher.fetch(
                prompt_name=phoenix_prompt_name,
                scope=self.__ctx.cloud,
                type="compliance",
                tag=system_config.environment,
            )
        return None
