# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Coroutine
from typing import Callable, Any

from src.application.exceptions import TerraformValidationFailedError
from src.application.services import ReportService
from src.domains.dto import TerraformValidationDTO
from src.domains.entities import History, SessionContext
from src.domains.interfaces import ITerraform
from src.domains.services import (
    TemplateOrchestrationService,
    SessionService,
    TerraformTargetService,
    TerraformValidationService,
)
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
    ):
        self.__validation_svc = validation_service
        self.__terraform_svc = terraform_service
        self.__session_svc = session_service
        self.__report_svc = report_service
        self.__template_svc = template_service
        self.__target_svc = target_service
        self.__ctx = session_ctx

    async def handle(self) -> Callable[[], Coroutine[Any, Any, None]]:
        ctx = self.__ctx

        async def background_task():
            try:
                _ = await self.__session_svc.update_status(
                    msg="Apply the IaC session changes",
                    prompt=await self.__template_svc.render(
                        PromptsLibrary.STATUS_UPDATE
                    ),
                    status=SessionStatus.APPLY,
                    history=ctx.history,
                )

                async def validation_callback(
                    history: History,
                ) -> TerraformValidationDTO:
                    return await self.__terraform_svc.apply(
                        targets=await self.__target_svc.generate(history)
                    )

                validation = await validation_callback(ctx.history)
                if not validation.validation:
                    validation = await self.__validation_svc.generate_and_validate(
                        q=validation.feedback,
                        ctx=ctx,
                        conventions=await self.__template_svc.compose_template(
                            query=validation.feedback,
                            history=ctx.history,
                        ),
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
                _ = await self.__report_svc.generate_report(
                    ctx=ctx,
                    type=ReportType.APPLY,
                    content=validation.terraform_plan,
                )
            finally:
                await self.__session_svc.save()

        return background_task
