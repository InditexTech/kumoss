# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.dto import ToolResultDTO
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.template_service import TemplateOrchestrationService
from src.domains.services.tool_service import ToolOrchestrationService
from src.shared.constants import PromptsLibrary, ToolContext
from src.shared.config import system_config


class TaskSplitService:
    """this service splits a single task into simpler self-contained operations
    example: create a storage account and a redis cache -> ["create a storage account", "create a redis cache"]
    """

    def __init__(
        self,
        llm_service: LLMOrchestrationService,
        template_service: TemplateOrchestrationService,
        tool_service: ToolOrchestrationService,
    ):
        self.__llm_svc = llm_service
        self.__template_svc = template_service
        self.__tool_svc = tool_service

    async def split_task(self, task: str) -> list[list[str]]:
        tools = self.__tool_svc.get_available_tools(
            contexts=[
                ToolContext.WORKSPACE_INSPECTION,
                ToolContext.EXTERNAL_INFORMATION,
            ]
        )
        response: ToolResultDTO = await self.__llm_svc.generate(
            query=task,
            tools=tools,
            sentinel_tool=self.__tool_svc.get_sentinel_tool(ToolContext.TASK_SPLITTER),
            prompt=await self.__template_svc.render(PromptsLibrary.TASK_SPLITTER),
        )
        ops: list[str] = response.result["operations"]
        return [
            ops[i : i + system_config.orchestration.drift_group_operations]
            for i in range(
                0, len(ops), system_config.orchestration.drift_group_operations
            )
        ]
