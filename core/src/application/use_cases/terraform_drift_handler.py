# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Coroutine
from typing import Callable, Any

from src.application.exceptions import SetLockError
from src.application.services.requests_filter_service import RequestsFilterService
from src.application.services.report_service import ReportService
from src.application.services.terraform_drift_service import TerraformDriftService
from src.domains.dto import TerraformValidationDTO
from src.domains.entities import History
from src.domains.entities.session import SessionContext
from src.domains.interfaces import ITerraform
from src.domains.services import (
    ComplianceCheckService,
    SessionService,
    TemplateOrchestrationService,
    TerraformValidationService,
    TerraformTargetService,
)
from src.domains.services.database_service import DatabaseService
from src.infrastructure.external.notification_service import NotificationServiceClient
from src.shared.config import system_config
from src.shared.constants import (
    PromptsLibrary,
    ReportType,
    SessionStatus,
)


class TerraformDriftHandler:
    def __init__(
        self,
        session_ctx: SessionContext,
        session_service: SessionService,
        terraform_service: ITerraform,
        validation_service: TerraformValidationService,
        template_service: TemplateOrchestrationService,
        requests_filter_service: RequestsFilterService,
        report_service: ReportService,
        target_service: TerraformTargetService,
        drift_service: TerraformDriftService,
        compliance_service: ComplianceCheckService,
    ):
        self.__terraform_svc = terraform_service
        self.__validation_svc = validation_service
        self.__session_svc = session_service
        self.__template_svc = template_service
        self.__report_svc = report_service
        self.__requests_filter_svc = requests_filter_service
        self.__target_svc = target_service
        self.__drift_svc = drift_service
        self.__compliance_svc = compliance_service
        self.__ctx = session_ctx

    async def handle(
        self, q: str, is_partial: bool
    ) -> Callable[[], Coroutine[Any, Any, None]]:
        ctx = self.__ctx

        async def background_task():
            try:
                await self.__session_svc.next_round(q)
                _ = await self.__session_svc.update_status(
                    msg=q,
                    prompt=await self.__template_svc.render(
                        PromptsLibrary.STATUS_UPDATE
                    ),
                    status=SessionStatus.FILTERING,
                    history=ctx.history,
                )
                conventions = await self.__template_svc.compose_template(q, ctx.history)

                targets = []
                if is_partial:
                    ok, rationale = await self.__requests_filter_svc.filter(
                        q, ctx.history, conventions, ctx.operation
                    )
                    if not ok:
                        ctx.history.append_turn(q, rationale)
                        _ = await self.__session_svc.update_status(
                            msg=rationale,
                            status=SessionStatus.UNCOMPLETED,
                        )
                        return
                    targets = await self.__target_svc.generate_drift(
                        query=q, history=ctx.history, conventions=conventions
                    )

                async def validation_callback(
                    local_history: History,
                ) -> TerraformValidationDTO:
                    return await self.__terraform_svc.validate(
                        targets=await self.__target_svc.generate_session(local_history),
                        get_drift=False,
                    )

                validation = await self.__drift_svc.detect_and_resolve_drift(
                    targets=targets,
                    conventions=conventions,
                    max_iterations=system_config.orchestration.max_drift_reports,
                    validator=validation_callback,
                )

                report = await self.__report_svc.generate_report(
                    ctx=ctx,
                    type=ReportType.DRIFT,
                    content=validation.terraform_plan,
                )
                check = await self.__compliance_svc.check(
                    history=ctx.history,
                    conventions=conventions,
                    report=report,
                )
                if not check.passed:
                    if not await DatabaseService.set_lock(ctx.id, True):
                        raise SetLockError(
                            message="Error updating DB session lock.",
                            error_code=500,
                        )
                    await NotificationServiceClient.notify_compliance_failure(
                        session_id=ctx.id,
                        summary=check.summary,
                    )
                elif not await DatabaseService.set_lock(ctx.id, False):
                    raise SetLockError(
                        message="Error updating DB session lock.",
                        error_code=500,
                    )
            finally:
                await self.__session_svc.save()

        return background_task
