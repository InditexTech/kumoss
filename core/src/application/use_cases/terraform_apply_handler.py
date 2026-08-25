# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Coroutine
from typing import Callable, Any

from src.application.exceptions import SetLockError, TerraformValidationFailedError
from src.application.services import ReportService
from src.domains.dto import TerraformValidationDTO
from src.domains.entities import History, SessionContext
from src.domains.interfaces import ITerraform
from src.domains.services import (
    ComplianceCheckService,
    TemplateOrchestrationService,
    SessionService,
    TerraformTargetService,
    TerraformValidationService,
)
from src.domains.services.database_service import DatabaseService
from src.domains.value_objects import Conventions
from src.infrastructure.external.notification_service import NotificationServiceClient
from src.shared.constants import (
    ReportType,
    SessionStatus,
    PromptsLibrary,
)


class TerraformApplyHandler:
    def __init__(
        self,
        terraform_service: ITerraform,
        session_service: SessionService,
        report_service: ReportService,
        template_service: TemplateOrchestrationService,
        validation_service: TerraformValidationService,
        target_service: TerraformTargetService,
        session_ctx: SessionContext,
        compliance_service: ComplianceCheckService,
    ):
        self.__validation_svc = validation_service
        self.__terraform_svc = terraform_service
        self.__session_svc = session_service
        self.__report_svc = report_service
        self.__template_svc = template_service
        self.__target_svc = target_service
        self.__compliance_svc = compliance_service
        self.__ctx = session_ctx

    async def handle(self) -> Callable[[], Coroutine[Any, Any, None]]:
        ctx = self.__ctx

        async def background_task():
            try:
                await self.__session_svc.next_round("Terraform apply.")

                async def validation_callback(
                    history: History,
                ) -> TerraformValidationDTO:
                    _ = await self.__session_svc.update_status(
                        msg="Apply the IaC session changes",
                        prompt=await self.__template_svc.render(
                            PromptsLibrary.STATUS_UPDATE
                        ),
                        status=SessionStatus.APPLY,
                        history=history,
                    )
                    return await self.__terraform_svc.apply(
                        targets=await self.__target_svc.generate(history)
                    )

                conventions = Conventions(templates=[], abbreviations=[])
                validation = await validation_callback(ctx.history)
                if not validation.validation:
                    conventions = await self.__template_svc.compose_template(
                        query=validation.feedback,
                        history=ctx.history,
                    )
                    validation = await self.__validation_svc.generate_and_validate(
                        q=validation.feedback,
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
                report = await self.__report_svc.generate_report(
                    ctx=ctx,
                    type=ReportType.APPLY,
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
            finally:
                await self.__session_svc.save()

        return background_task
