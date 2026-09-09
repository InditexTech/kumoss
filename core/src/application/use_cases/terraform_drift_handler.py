# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Coroutine
import json
from typing import Callable, Any

from src.application.exceptions import SetLockError
from src.application.services.requests_filter_service import RequestsFilterService
from src.application.services.report_service import ReportService
from src.application.services.terraform_drift_service import TerraformDriftService
from src.domains.entities.session import SessionContext
from src.domains.services import (
    SessionService,
    TemplateOrchestrationService,
    TerraformTargetService,
)
from src.domains.services.database_service import DatabaseService
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
        template_service: TemplateOrchestrationService,
        requests_filter_service: RequestsFilterService,
        report_service: ReportService,
        target_service: TerraformTargetService,
        drift_service: TerraformDriftService,
    ):
        self.__session_svc = session_service
        self.__template_svc = template_service
        self.__report_svc = report_service
        self.__requests_filter_svc = requests_filter_service
        self.__target_svc = target_service
        self.__drift_svc = drift_service
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
                targets = []
                if is_partial:
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

                if is_partial:
                    targets = await self.__target_svc.generate_drift(
                        query=q, history=ctx.history, conventions=conventions
                    )

                validation = await self.__drift_svc.detect_and_resolve_drift(
                    filter_session_changes=False,
                    targets=targets,
                    conventions=conventions,
                    max_iterations=system_config.orchestration.max_drift_reports,
                )
                content: str = json.dumps(ctx.history.serialize())
                if not validation.validation:
                    content += f"\n\nPlease note, this drift couldn't be reconcile: {validation.feedback}"

                _ = await self.__report_svc.generate_report(
                    ctx=ctx,
                    type=ReportType.DRIFT,
                    content=content,
                )
                if not await DatabaseService.set_lock(ctx.id, False):
                    raise SetLockError(
                        message="Error updating DB session lock.",
                        error_code=500,
                    )
            finally:
                await self.__session_svc.save()

        return background_task
