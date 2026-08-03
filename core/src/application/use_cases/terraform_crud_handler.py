# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Coroutine
from typing import Callable, Any

from src.application.services.filter_request_service import FilterRequestService
from src.application.services.report_service import ReportService
from src.application.services.terraform_drift_service import TerraformDriftService
from src.domains.entities.session import SessionContext
from src.domains.services import (
    SessionService,
    TracerService,
    TemplateOrchestrationService,
    TerraformValidationService,
    TerraformTargetService,
)
from src.infrastructure.telemetry.phoenix.phoenix_tracer import PhoenixTracer
from src.shared.constants import ReportType, SessionStatus
from src.shared.exceptions import ExceptionHandler


class TerraformCRUDHandler:
    def __init__(
        self,
        session_service: SessionService,
        validation_service: TerraformValidationService,
        template_service: TemplateOrchestrationService,
        filter_request_service: FilterRequestService,
        report_svc: ReportService,
        target_svc: TerraformTargetService,
        drift_svc: TerraformDriftService,
        session_ctx: SessionContext,
    ):
        self.__validation_svc = validation_service
        self.__session_svc = session_service
        self.__template_svc = template_service
        self.__report_svc = report_svc
        self.__filter_request_svc = filter_request_service
        self.__target_svc = target_svc
        self.__drift_svc = drift_svc
        self.__ctx = session_ctx

    async def handle(self, q: str) -> Callable[[], Coroutine[Any, Any, None]]:
        ctx = self.__ctx
        local_hist = ctx.history.deepcopy()

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
                await self.__session_svc.next_round_id(q)

                ok, explanation = await self.__filter_request_svc.filter(q, local_hist)
                if not ok:
                    ctx.history.append_turn(q, explanation)
                    await self.__session_svc.update_status(
                        msg=explanation,
                        status=SessionStatus.UNCOMPLETED,
                    )
                    return

                predictive_targets = await self.__target_svc.generate_predictive(
                    query=q, history=ctx.history, include_forbidden_actions=True
                )
                if predictive_targets:
                    _ = await self.__drift_svc.detect_and_resolve_drift(
                        targets=predictive_targets,
                        max_iterations=2,
                    )

                _ = await self.__validation_svc.generate_and_validate(
                    query=q, ctx=ctx, include_forbidden_actions=True
                )
                _ = await self.__report_svc.generate_report(
                    type=ReportType.GENERATE,
                    query=q,
                    history=local_hist,
                )
            except ExceptionHandler as e:
                await self.__session_svc.update_status(
                    msg=e.message, status=SessionStatus.FAILED
                )
                raise
            finally:
                TracerService.reset_current_tracer(tracer_token)

        return background_task
