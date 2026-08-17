# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Coroutine
from typing import Callable, Any

from src.application.exceptions import TerraformValidationFailedError
from src.application.services import ReportService
from src.domains.entities import SessionContext
from src.domains.interfaces import ITerraform
from src.domains.services import (
    TemplateOrchestrationService,
    SessionService,
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
        session_ctx: SessionContext,
    ):
        self.__terraform_svc = terraform_service
        self.__session_svc = session_service
        self.__report_svc = report_service
        self.__template_svc = template_service
        self.__ctx = session_ctx

    async def handle(
        self, q: str, terraform_targets: list[str]
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
                    status=SessionStatus.APPLY,
                )

                validation = await self.__terraform_svc.apply(
                    targets=terraform_targets,
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

