# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from collections.abc import Coroutine
from typing import Callable, Any, cast

from src.application.exceptions import TerraformValidationFailedError
from src.application.services import ReportService
from src.domains.dto import TerraformApplyReport
from src.domains.entities import SessionContext
from src.domains.interfaces import ITerraform, IWorkspace
from src.domains.services import (
    ComplianceCheckService,
    TemplateOrchestrationService,
    SessionService,
)
from src.infrastructure.external.notification_service import NotificationServiceClient
from src.shared.constants import (
    ReportType,
    SessionStatus,
    PromptsLibrary,
)


class TerraformApplyHandler:
    """Apply the session's pinned plan — nothing more.

    The plan was validated and reviewed by the generate round that
    pinned its workspace; this handler executes exactly that artifact.
    Only a new generate round can produce the next appliable plan —
    drift rounds never pin one.
    """

    def __init__(
        self,
        terraform_service: ITerraform,
        session_service: SessionService,
        report_service: ReportService,
        template_service: TemplateOrchestrationService,
        session_ctx: SessionContext,
        compliance_service: ComplianceCheckService,
        workspace_service: IWorkspace,
    ):
        self.__terraform_svc = terraform_service
        self.__session_svc = session_service
        self.__report_svc = report_service
        self.__template_svc = template_service
        self.__compliance_svc = compliance_service
        self.__workspace_svc = workspace_service
        self.__ctx = session_ctx

    async def handle(self) -> Callable[[], Coroutine[Any, Any, None]]:
        ctx = self.__ctx

        async def background_task():
            try:
                q = "Apply the IaC session changes"
                await self.__session_svc.next_round("Terraform apply.")
                _ = await self.__session_svc.update_status(
                    msg=q,
                    prompt=await self.__template_svc.render(
                        PromptsLibrary.STATUS_UPDATE
                    ),
                    status=SessionStatus.APPLY,
                    history=ctx.history,
                )
                if self.__workspace_svc.pinned_plan_path(ctx.id) is None:
                    raise TerraformValidationFailedError(
                        message="No reviewed plan is pinned for this session; "
                        + "run a generate round before applying.",
                        error_code=409,
                    )
                validation = await self.__terraform_svc.apply()
                report: TerraformApplyReport = cast(
                    TerraformApplyReport,
                    await self.__report_svc.generate_report(
                        ctx=ctx,
                        type=ReportType.APPLY,
                        content=validation.terraform_plan + validation.feedback,
                    ),
                )
                ctx.history.append_turn(q, report.execution_summary)
                if not validation.validation:
                    await NotificationServiceClient.notify_apply_failure(
                        ctx.id, ctx.user_id, report.execution_summary
                    )
            finally:
                self.__workspace_svc.discard_pinned(ctx.id)
                await self.__session_svc.save()

        return background_task
