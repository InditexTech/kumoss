# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Coroutine
from typing import Callable, Any, Literal

from src.domains.dto import ComplianceContextDTO
from src.clients.notifications_factory import get_notifications_client
from src.clients.notifications.api.notify import notify as notify_api
from src.clients.notifications.models.notification_request import NotificationRequest
from src.clients.notifications.models.notification_request_severity import (
    NotificationRequestSeverity,
)
from src.domains.entities.session import SessionContext
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
from src.shared.constants import SessionStatus, PromptsLibrary
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging


class ComplianceCheckHandler:
    def __init__(
        self,
        compliance_service: ComplianceCheckService,
        session_service: SessionService,
        template_service: TemplateOrchestrationService,
        session_ctx: SessionContext,
        mode: Literal["plan_vs_core", "plan_vs_custom"] = "plan_vs_core",
        phoenix_prompt_name: str | None = None,
    ):
        self.__compliance_svc = compliance_service
        self.__session_svc = session_service
        self.__template_svc = template_service
        self.__ctx = session_ctx
        self.__mode = mode
        self.__phoenix_prompt_name = phoenix_prompt_name

    async def __resolve_rules(self) -> str | None:
        if self.__mode == "plan_vs_custom" and self.__phoenix_prompt_name:
            scope = self.__ctx.terraform_prv.value if self.__ctx.terraform_prv else "general"
            return await remote_fetcher.fetch(
                prompt_name=self.__phoenix_prompt_name,
                scope=scope,
                type="compliance",
                tag=system_config.environment,
            )
        return None

    async def handle(self) -> Callable[[], Coroutine[Any, Any, None]]:
        ctx = self.__ctx

        async def background_task():
            tracer_token = TracerService.set_current_tracer(
                tracer=PhoenixTracer(
                    session_id=ctx.id,
                    user_id=ctx.user_id,
                    branch_name=ctx.branch_name,
                    cloud=ctx.terraform_prv,
                    iac_path=ctx.iac_path,
                )
            )
            try:
                await self.__session_svc.update_status(
                    msg="Running compliance check",
                    prompt=await self.__template_svc.render(
                        PromptsLibrary.STATUS_UPDATE
                    ),
                    status=SessionStatus.VALIDATING,
                )

                rules = await self.__resolve_rules()
                context = ComplianceContextDTO(rules=rules)

                report = await self.__compliance_svc.check(context=context)
                report_dict = report.model_dump() if hasattr(report, "model_dump") else report
                passed = report.passed if hasattr(report, "passed") else report["passed"]
                summary = report.summary if hasattr(report, "summary") else report["summary"]

                if not passed:
                    await DatabaseService.set_lock(ctx.id, lock=True)
                    await self.__notify_failure(ctx, report_dict)

                await self.__session_svc.update_status(
                    msg=summary,
                    status=SessionStatus.COMPLETED if passed else SessionStatus.FAILED,
                )
            except ExceptionHandler as e:
                await self.__session_svc.update_status(
                    msg=e.message, status=SessionStatus.FAILED
                )
                raise
            finally:
                TracerService.reset_current_tracer(tracer_token)

        return background_task

    @staticmethod
    async def __notify_failure(
        ctx: SessionContext, report: dict[str, Any]
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
                    subject=f"Compliance check failed – session {ctx.id}",
                    body=report["summary"],
                ),
            )
        except Exception:
            logging.warning(
                f"Failed to send compliance-failure notification for session {ctx.id}"
            )
