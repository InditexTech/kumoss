# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.entities.history import History
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.template_service import TemplateOrchestrationService
from src.domains.services.tool_service import ToolOrchestrationService
from src.domains.dto import ToolDefinitionDTO, ToolResultDTO
from src.domains.value_objects import Conventions
from src.shared.constants import TargetGenerationMode, ToolContext, PromptsLibrary


class TerraformTargetService:
    def __init__(
        self,
        tool_service: ToolOrchestrationService,
        llm_service: LLMOrchestrationService,
        template_service: TemplateOrchestrationService,
    ):
        self.__tool_svc = tool_service
        self.__llm_svc = llm_service
        self.__template_svc = template_service

    async def generate(self, history: History, query: str = None) -> list[str]:
        tools_definition: list[ToolDefinitionDTO] = self.__tool_svc.get_available_tools(
            contexts=[ToolContext.WORKSPACE_INSPECTION]
        )
        response: ToolResultDTO = await self.__llm_svc.generate(
            query=query or "Generate the relevant Terraform targets.",
            tools=tools_definition,
            sentinel_tool=self.__tool_svc.get_sentinel_tool(
                ToolContext.TARGET_GENERATOR
            ),
            prompt=await self.__template_svc.render(
                PromptsLibrary.TARGET_GENERATOR,
                mode=TargetGenerationMode.SESSION,
            ),
            history=history,
        )
        return response.result["targets"]

    async def generate_predictive(
        self,
        query: str,
        history: History,
        conventions: Conventions,
    ) -> list[str]:

        tools_definition: list[ToolDefinitionDTO] = self.__tool_svc.get_available_tools(
            contexts=[
                ToolContext.WORKSPACE_INSPECTION,
                ToolContext.EXTERNAL_INFORMATION,
            ]
        )
        response: ToolResultDTO = await self.__llm_svc.generate(
            query=query,
            tools=tools_definition,
            sentinel_tool=self.__tool_svc.get_sentinel_tool(
                ToolContext.TARGET_GENERATOR
            ),
            prompt=await self.__template_svc.render(
                prompt=PromptsLibrary.TARGET_GENERATOR,
                mode=TargetGenerationMode.PREDICTIVE,
                resources=conventions.templates,
            ),
            history=history,
        )
        return response.result["targets"]

    async def generate_drift(
        self,
        query: str,
        history: History,
        conventions: Conventions,
    ) -> list[str]:

        tools_definition: list[ToolDefinitionDTO] = self.__tool_svc.get_available_tools(
            contexts=[
                ToolContext.WORKSPACE_INSPECTION,
            ]
        )
        response: ToolResultDTO = await self.__llm_svc.generate(
            query=query,
            tools=tools_definition,
            sentinel_tool=self.__tool_svc.get_sentinel_tool(
                ToolContext.DRIFT_TARGET_GENERATOR
            ),
            prompt=await self.__template_svc.render(
                prompt=PromptsLibrary.TARGET_GENERATOR,
                mode=TargetGenerationMode.DRIFT_REMEDIATION,
                resources=conventions.templates,
            ),
            history=history,
        )
        return response.result["targets"]
