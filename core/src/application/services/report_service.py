# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.application.exceptions import ReportGenerationError
from src.domains.dto import (
    TerraformApplyReport,
    TerraformDriftReport,
    TerraformPlanReport,
    ToolResultDTO,
)
from src.domains.entities.history import History
from src.domains.services import SessionService
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.template_service import TemplateOrchestrationService
from src.domains.services.tool_service import ToolOrchestrationService
from src.shared.constants import ReportType, SessionStatus, ToolContext, PromptsLibrary

_Report = TerraformPlanReport | TerraformDriftReport | TerraformApplyReport


class ReportService:
    def __init__(
        self,
        second_llm_service: LLMOrchestrationService,
        tool_service: ToolOrchestrationService,
        template_service: TemplateOrchestrationService,
        session_service: SessionService,
    ):
        self.__llm_svc = second_llm_service
        self.__tool_svc = tool_service
        self.__template_svc = template_service
        self.__session_svc = session_service

    async def generate_report(
        self,
        report_type: ReportType,
        query: str,
        history: History,
    ) -> _Report:
        tool_index = {
            ReportType.GENERATE: 0,
            ReportType.DRIFT: 1,
            ReportType.APPLY: 2,
        }.get(report_type, 0)

        await self.__session_svc.update_status(
            msg="Infrastructure successfully validated. Generating report.",
            prompt=await self.__template_svc.render(PromptsLibrary.STATUS_UPDATE),
            status=SessionStatus.REPORT,
            history=history,
        )
        response: ToolResultDTO = await self.__llm_svc.generate(
            query=query,
            tools=[
                self.__tool_svc.get_available_tools([ToolContext.REPORT_GENERATOR])[
                    tool_index
                ]
            ],
            prompt=await self.__template_svc.render(
                PromptsLibrary.REPORT_GENERATOR,
                report_type=report_type,
            ),
        )
        if not response.success:
            raise ReportGenerationError(
                f"report '{report_type}' generation error.", 500
            )
        return response.result
