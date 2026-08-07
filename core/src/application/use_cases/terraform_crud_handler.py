# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Coroutine
from typing import Callable, Any

from src.application.exceptions import TerraformValidationFailedError
from src.application.services.requests_filter_service import RequestsFilterService
from src.application.services.report_service import ReportService
from src.application.services.terraform_drift_service import TerraformDriftService
from src.domains.entities.session import SessionContext
from src.domains.services import (
    SessionService,
    TemplateOrchestrationService,
    TerraformValidationService,
    TerraformTargetService,
)
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
        validation_service: TerraformValidationService,
        template_service: TemplateOrchestrationService,
        requests_filter_service: RequestsFilterService,
        report_service: ReportService,
        target_service: TerraformTargetService,
        drift_service: TerraformDriftService,
    ):
        self.__validation_svc = validation_service
        self.__session_svc = session_service
        self.__template_svc = template_service
        self.__report_svc = report_service
        self.__requests_filter_svc = requests_filter_service
        self.__target_svc = target_service
        self.__drift_svc = drift_service
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
                )
                conventions = await self.__template_svc.compose_template(q, ctx.history)

                ok, rationale = await self.__requests_filter_svc.filter(
                    q, ctx.history, conventions
                )
                if not ok:
                    ctx.history.append_turn(q, rationale)
                    _ = await self.__session_svc.update_status(
                        msg=rationale,
                        status=SessionStatus.UNCOMPLETED,
                    )
                    return

                _ = await self.__session_svc.update_status(
                    msg=q,
                    prompt=await self.__template_svc.render(
                        PromptsLibrary.STATUS_UPDATE
                    ),
                    status=SessionStatus.GENERATING,
                )

                predictive_targets = await self.__target_svc.generate_predictive(
                    query=q,
                    history=ctx.history,
                    conventions=conventions,
                    include_forbidden_actions=True,
                )
                if predictive_targets:
                    _ = await self.__drift_svc.detect_and_resolve_drift(
                        targets=predictive_targets,
                        conventions=conventions,
                        max_iterations=2,
                    )

                validation = await self.__validation_svc.generate_and_validate(
                    q=q,
                    ctx=ctx,
                    conventions=conventions,
                    include_forbidden_actions=True,
                )
                if not validation.validation:
                    fail_msg = self.__report_svc.summarize_problem(
                        feedback=validation.feedback,
                        history=ctx.history,
                    )
                    raise TerraformValidationFailedError(
                        message=fail_msg,
                        error_code=500,
                    )
                _ = await self.__report_svc.generate_report(
                    ctx=ctx,
                    type=ReportType.GENERATE,
                    content=validation.terraform_plan,
                )
            finally:
                await self.__session_svc.save()

        return background_task
