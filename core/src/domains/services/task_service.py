# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import json

from src.domains.dto import FilteredImportsDTO, FilteredOperationsDTO
from src.domains.entities import History
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.template_service import TemplateOrchestrationService
from src.domains.services.tool_service import ToolOrchestrationService
from src.domains.value_objects import Conventions
from src.shared.constants import OperationType, PromptsLibrary, ToolContext
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

    async def split_task(
        self, task: str, operation_type: OperationType
    ) -> list[list[str]]:
        response = await self.__llm_svc.generate(
            query=task,
            prompt=await self.__template_svc.render(
                PromptsLibrary.TASK_SPLITTER, operation_type=operation_type
            ),
            tools=self.__tool_svc.get_available_tools(
                contexts=[
                    ToolContext.WORKSPACE_INSPECTION,
                    ToolContext.EXTERNAL_INFORMATION,
                ]
            ),
            sentinel_tool=self.__tool_svc.get_sentinel_tool(ToolContext.TASK_SPLITTER),
        )
        return self.__group(response.result["operations"])

    async def split_errors(self, errors: str, operation_type: OperationType) -> str:
        """Turn a failed validation's errors into the next generation query.

        The operations lead, in the order the splitter fixed for them, and
        the raw errors follow so file names and line numbers survive the
        rewording. An empty split leaves the errors as they came.
        """
        operations = [
            op
            for group in await self.split_task(
                task=errors, operation_type=operation_type
            )
            for op in group
        ]
        if not operations:
            return errors
        steps = "\n".join(f"{i}. {op}" for i, op in enumerate(operations, 1))
        return f"Fix the following errors:\n{steps}\n\n"

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

    async def filter_exceptions(
        self, operations: list[list[str]]
    ) -> FilteredOperationsDTO:
        flat_operations: list[str] = [op for group in operations for op in group]
        if not flat_operations:
            return FilteredOperationsDTO(kept=[], excluded=[], explanation="")
        response = await self.__llm_svc.generate(
            query=json.dumps(flat_operations),
            prompt=await self.__template_svc.render(
                PromptsLibrary.FILTER_DRIFT_EXCEPTIONS
            ),
            tools=[self.__tool_svc.get_sentinel_tool(ToolContext.TASK_SPLITTER)],
        )
        kept: list[str] = response.result["operations"]
        return FilteredOperationsDTO(
            kept=self.__group(kept),
            excluded=[op for op in flat_operations if op not in kept],
            explanation=response.result.get("explanation", ""),
        )

    async def filter_imports(
        self,
        query: str,
        unmanaged_ids: list[str],
        conventions: Conventions,
        history: History,
    ) -> FilteredImportsDTO:
        """Narrow a scope's unmanaged resources to the ones a request asks for.

        The conventions travel with the query because the agent matches a
        request phrased in the repository's own vocabulary — template
        names and resource name abbreviations — against provider-native
        resource ids, which carry none of it.
        """
        if not unmanaged_ids:
            return FilteredImportsDTO(selected=[], explanation="")
        response = await self.__llm_svc.generate(
            query=query,
            tools=[self.__tool_svc.get_sentinel_tool(ToolContext.TASK_SPLITTER)],
            prompt=await self.__template_svc.render(
                prompt=PromptsLibrary.IMPORT_FILTER,
                unmanaged_ids=unmanaged_ids,
                resources=conventions.templates,
                abbreviations=conventions.abbreviations,
            ),
            history=history,
        )
        return FilteredImportsDTO(
            selected=response.result["operations"],
            explanation=response.result.get("explanation", ""),
        )

    def __group(self, ops: list[str]) -> list[list[str]]:
        size = system_config.orchestration.drift_group_operations
        return [ops[i : i + size] for i in range(0, len(ops), size)]
