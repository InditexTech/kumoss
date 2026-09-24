# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.dto import ComplianceCheckReport, ToolResultDTO
from src.domains.entities import SessionContext
from src.domains.services.artifact_storage_service import ArtifactStorageService
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.template_service import TemplateOrchestrationService
from src.domains.services.tool_service import ToolOrchestrationService
from src.domains.value_objects import Conventions
from src.shared.config import system_config
from src.shared.constants import ContentType, PromptsLibrary, ToolContext


class ComplianceCheckService:
    def __init__(
        self,
        tool_service: ToolOrchestrationService,
        llm_service: LLMOrchestrationService,
        template_service: TemplateOrchestrationService,
        artifact_service: ArtifactStorageService,
    ):
        self.__tool_svc = tool_service
        self.__llm_svc = llm_service
        self.__template_svc = template_service
        self.__artifact_svc = artifact_service

    async def check(
        self,
        ctx: SessionContext,
        conventions: Conventions,
        plan: str,
    ) -> ComplianceCheckReport:
        if not system_config.orchestration.enable_compliance_checker:
            return ComplianceCheckReport.empty()

        query: str = (
            "The user request:\n"
            f"{ctx.history.get_first_turn().user}\n\n"
            "The Terraform plan to audit:\n"
            f"{plan}"
        )

        result: ToolResultDTO = await self.__llm_svc.generate(
            query=query,
            tools=self.__tool_svc.get_available_tools(
                contexts=[ToolContext.COMPLIANCE_CHECK]
            ),
            prompt=await self.__template_svc.render(
                PromptsLibrary.COMPLIANCE_CHECKER,
                resources=conventions.templates,
                abbreviations=conventions.abbreviations,
            ),
        )

        report: ComplianceCheckReport = result.result
        _ = await self.__artifact_svc.store_compliance_check(
            session_id=ctx.id,
            round_id=ctx.round_id,
            passed=report.passed,
            content=report.model_dump_json(),
            content_type=ContentType.JSON,
        )
        return report
