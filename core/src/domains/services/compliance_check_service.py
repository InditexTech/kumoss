# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.dto import ComplianceCheckReport, Reports, ToolResultDTO
from src.domains.entities import History
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.template_service import TemplateOrchestrationService
from src.domains.services.tool_service import ToolOrchestrationService
from src.domains.value_objects import Conventions
from src.shared.config import system_config
from src.shared.constants import PromptsLibrary, ToolContext


class ComplianceCheckService:
    def __init__(
        self,
        tool_service: ToolOrchestrationService,
        llm_service: LLMOrchestrationService,
        template_service: TemplateOrchestrationService,
    ):
        self.__tool_svc = tool_service
        self.__llm_svc = llm_service
        self.__template_svc = template_service

    async def check(
        self,
        history: History,
        conventions: Conventions,
        report: Reports,
    ) -> ComplianceCheckReport:
        if not system_config.orchestration.enable_compliance_checker:
            return ComplianceCheckReport.empty()

        query = (
            "Audit the generated report below and report your findings via "
            "`report_compliance_findings`.\n\n"
            f"The generated report to audit:\n{report.model_dump_json()}"
        )

        result: ToolResultDTO = await self.__llm_svc.generate(
            query=query,
            tools=self.__tool_svc.get_available_tools(
                contexts=[ToolContext.WORKSPACE_INSPECTION]
            ),
            sentinel_tool=self.__tool_svc.get_sentinel_tool(
                ToolContext.COMPLIANCE_CHECK
            ),
            prompt=await self.__template_svc.render(
                PromptsLibrary.COMPLIANCE_CHECKER,
                resources=conventions.templates,
                abbreviations=conventions.abbreviations,
            ),
            history=history,
        )

        return result.result
