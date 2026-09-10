# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Coroutine
from typing import Callable, Any

from src.application.exceptions import SetLockError, TerraformValidationFailedError
from src.application.services.requests_filter_service import RequestsFilterService
from src.application.services.report_service import ReportService
from src.application.services.terraform_drift_service import TerraformDriftService
from src.domains.dto import TerraformValidationDTO
from src.domains.entities import History
from src.domains.entities.session import SessionContext
from src.domains.interfaces import ITerraform, IWorkspace
from src.domains.services import (
    ComplianceCheckService,
    SessionService,
    TemplateOrchestrationService,
    TerraformValidationService,
    TerraformTargetService,
)
from src.domains.services.database_service import DatabaseService
from src.infrastructure.external.notification_service import NotificationServiceClient
from src.shared.constants import (
    PromptsLibrary,
    ReportType,
    SessionStatus,
)


class TerraformCRUDHandler:
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
        workspace_service: IWorkspace,
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
        self.__workspace_svc = workspace_service
        self.__ctx = session_ctx

    async def handle(self, q: str) -> Callable[[], Coroutine[Any, Any, None]]:
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
                ok, rationale = await self.__requests_filter_svc.filter(
                    q, ctx.history, ctx.operation
                )
                if not ok:
                    ctx.history.append_turn(q, rationale)
                    _ = await self.__session_svc.update_status(
                        msg=rationale,
                        status=SessionStatus.UNCOMPLETED,
                    )
                    return

                conventions = await self.__template_svc.compose_template(q, ctx.history)

                async def validation_callback(
                    local_history: History,
                ) -> TerraformValidationDTO:
                    return await self.__terraform_svc.validate(
                        targets=await self.__target_svc.generate_session(local_history),
                        get_drift=False,
                    )

                validation = await self.__validation_svc.generate_and_validate(
                    q=q,
                    ctx=ctx,
                    conventions=conventions,
                    include_forbidden_actions=True,
                    validator=validation_callback,
                )

                if not validation.validation:
                    fail_msg = await self.__report_svc.summarize_problem(
                        feedback=validation.feedback,
                        history=ctx.history,
                    )
                    raise TerraformValidationFailedError(
                        message=fail_msg,
                        error_code=500,
                    )

                validation = await self.__drift_svc.detect_and_resolve_drift(
                    filter_session_changes=True,
                    targets=validation.terraform_targets,
                    conventions=conventions,
                    max_iterations=2,
                )

                _ = await self.__report_svc.generate_report(
                    ctx=ctx,
                    type=ReportType.GENERATE,
                    content=validation.terraform_plan,
                )

                check = await self.__compliance_svc.check(
                    request=ctx.history.get_first_turn().user,
                    conventions=conventions,
                    plan=validation.terraform_plan,
                )
                if not check.passed:
                    if not await DatabaseService.set_lock(ctx.id, True):
                        raise SetLockError(
                            message="Error updating DB session lock.",
                            error_code=500,
                        )
                    await NotificationServiceClient.notify_compliance_failure(
                        ctx.id, ctx.user_id, check.summary
                    )
                elif not await DatabaseService.set_lock(ctx.id, False):
                    raise SetLockError(
                        message="Error updating DB session lock.",
                        error_code=500,
                    )
                self.__workspace_svc.pin_workspace(ctx.id, ctx.call_dir)
            finally:
                await self.__session_svc.save()

        return background_task
