# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Any

from src.domains.dto import ComplianceContextDTO, ToolDefinitionDTO, ToolResultDTO
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.template_service import TemplateOrchestrationService
from src.domains.services.tool_service import ToolOrchestrationService
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
        output_under_check: str | None = None,
        context: ComplianceContextDTO | None = None,
    ) -> Any:
        tools: list[ToolDefinitionDTO] = self.__tool_svc.get_available_tools(
            contexts=[ToolContext.WORKSPACE_INSPECTION]
        )
        sentinel = self.__tool_svc.get_sentinel_tool(ToolContext.COMPLIANCE_CHECK)

        rules = context.rules if context else None
        prompt = await self.__template_svc.render(
            PromptsLibrary.COMPLIANCE_CHECKER, **({"rules": rules} if rules else {})
        )

        check_target = output_under_check or (
            context.output_under_check if context else None
        )
        if check_target:
            query = (
                "Run a compliance check on the following Terraform plan:\n\n"
                + check_target
            )
        else:
            query = "Run a compliance check on the workspace files."

        result: ToolResultDTO = await self.__llm_svc.generate(
            query=query,
            tools=tools,
            sentinel_tool=sentinel,
            prompt=prompt,
        )

        return result.result
