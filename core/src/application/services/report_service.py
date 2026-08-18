# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import cast

from src.application.exceptions import ReportGenerationError
from src.domains.dto import Reports, ToolResultDTO
from src.domains.entities import SessionContext
from src.domains.entities.history import History
from src.domains.services import ArtifactStorageService, SessionService
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.template_service import TemplateOrchestrationService
from src.domains.services.tool_service import ToolOrchestrationService
from src.shared.constants import (
    ContentType,
    ReportType,
    SessionStatus,
    ToolContext,
    PromptsLibrary,
)


class ReportService:
    def __init__(
        self,
        second_llm_service: LLMOrchestrationService,
        tool_service: ToolOrchestrationService,
        template_service: TemplateOrchestrationService,
        session_service: SessionService,
        artifact_service: ArtifactStorageService,
    ):
        self.__llm_svc = second_llm_service
        self.__tool_svc = tool_service
        self.__template_svc = template_service
        self.__session_svc = session_service
        self.__artifact_svc = artifact_service

    async def generate_report(
        self,
        ctx: SessionContext,
        type: ReportType,
        content: str,
    ) -> Reports:
        tool_index = {
            ReportType.GENERATE: 0,
            ReportType.DRIFT: 1,
            ReportType.APPLY: 2,
        }.get(type)

        _ = await self.__session_svc.update_status(
            msg="Infrastructure successfully validated. Generating report",
            prompt=await self.__template_svc.render(PromptsLibrary.STATUS_UPDATE),
            status=SessionStatus.REPORT,
            history=ctx.history,
        )
        response: ToolResultDTO = await self.__llm_svc.generate(
            query=content,
            tools=[
                self.__tool_svc.get_available_tools([ToolContext.REPORT_GENERATOR])[
                    tool_index
                ]
            ],
            prompt=await self.__template_svc.render(
                PromptsLibrary.REPORT_GENERATOR,
                report_type=type,
            ),
        )
        if not response.success:
            raise ReportGenerationError(f"report '{type}' generation error.", 500)
        _ = await self.__artifact_svc.store_report(
            session_id=ctx.id,
            round_id=ctx.round_id,
            report_type=type,
            content=cast(Reports, response.result).model_dump_json(),
            content_type=ContentType.JSON,
        )
        return response.result

    async def summarize_problem(self, feedback: str, history: History) -> str:
        return await self.__llm_svc.generate_text(
            query=f"The IaC generated could not be validated: {feedback}",
            prompt=await self.__template_svc.render(PromptsLibrary.STATUS_UPDATE),
            history=history,
        )
