# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import json

from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.template_service import TemplateOrchestrationService
from src.domains.services.tool_service import ToolOrchestrationService
from src.shared.constants import PromptsLibrary, ToolContext
from src.shared.config import system_config


class TaskService:
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
        response = await self.__llm_svc.generate(
            query=task,
            prompt=await self.__template_svc.render(PromptsLibrary.TASK_SPLITTER),
            tools=self.__tool_svc.get_available_tools(
                [
                    ToolContext.WORKSPACE_INSPECTION,
                    ToolContext.EXTERNAL_INFORMATION,
                ]
            ),
            sentinel_tool=self.__tool_svc.get_sentinel_tool(ToolContext.TASK_SPLITTER),
        )
        return self.__group(response.result["operations"])

    async def filter_reconciliation(
        self, operations: list[list[str]]
    ) -> list[list[str]]:
        flat_operations: list[str] = [op for group in operations for op in group]
        if not flat_operations:
            return []
        response = await self.__llm_svc.generate(
            query=json.dumps(flat_operations),
            prompt=await self.__template_svc.render(
                PromptsLibrary.FILTER_RECONCILIATION
            ),
            tools=self.__tool_svc.get_available_tools(ToolContext.WORKSPACE_INSPECTION),
            sentinel_tool=self.__tool_svc.get_sentinel_tool(ToolContext.TASK_SPLITTER),
        )
        return self.__group(response.result["operations"])

    def __group(self, ops: list[str]) -> list[list[str]]:
        size = system_config.orchestration.drift_group_operations
        return [ops[i : i + size] for i in range(0, len(ops), size)]
