# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import json
import inspect
from pathlib import Path
from typing import Any, Callable, override

from src.domains.interfaces import IToolRegistry, IFileSystem, IGit
from src.domains.dto import (
    TerraformDriftReport,
    ToolCallDTO,
    ToolResultDTO,
    ToolDefinitionDTO,
    TerraformPlanReport,
    TerraformApplyReport,
)
from src.infrastructure.external.gemini_web_search import GeminiWebSearch
from src.infrastructure.exceptions import (
    ToolDefinitionContextNotFound,
    ToolDefinitionNameNotFound,
    ToolInferenceParamsError,
)
from src.shared.constants import ToolContext
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging


class ToolRegistry(IToolRegistry):
    def __init__(
        self,
        filesystem: IFileSystem,
        git: IGit,
        web_search: GeminiWebSearch,
    ):
        self.__filesystem = filesystem
        self.__git = git
        self.__web_search = web_search
        self.__tools_directory = Path(__file__).parent
        self.__tool_definitions: dict[str, ToolDefinitionDTO] = {}
        self.__tool_handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}
        self.__load_tools()
        self.__register_handlers()

    def __load_tools(self):
        """Load tool definitions from JSON files"""
        tool_files = {
            "file_manipulation.json": ToolContext.FILE_OPERATIONS,
            "workspace_inspection.json": ToolContext.WORKSPACE_INSPECTION,
            "requests_filter.json": ToolContext.REQUESTS_FILTER,
            "task_splitter.json": ToolContext.TASK_SPLITTER,
            "prompt_compositor.json": ToolContext.PROMPT_COMPOSITOR,
            "target_generator.json": ToolContext.TARGET_GENERATOR,
            "report_generator.json": ToolContext.REPORT_GENERATOR,
            "external_information.json": ToolContext.EXTERNAL_INFORMATION,
            "task_completion.json": ToolContext.GENERAL_TASK_COMPLETION,
        }

        for filename, context in tool_files.items():
            file_path = self.__tools_directory / filename
            if file_path.exists():
                self.__load_tool_file(file_path, context)

    def __load_tool_file(self, file_path: Path, context: ToolContext):
        """Load tools from a single JSON file"""
        with open(file_path, "r") as f:
            tools_data = json.load(f)

        for tool_data in tools_data:
            tool_def = ToolDefinitionDTO(
                name=tool_data["name"],
                description=tool_data["description"],
                parameters=tool_data["parameters"],
                context=context,
            )
            self.__tool_definitions[tool_def.name] = tool_def
            logging.info(f"Loaded tool: {tool_def.name} from {file_path.name}")

    def __register_handlers(self):
        """Register tool execution handlers"""
        self.__tool_handlers = {
            # File operations
            "write_to_file": self.__handle_write_file,
            "replace_in_file": self.__handle_replace_file,
            "delete_file": self.__handle_delete_file,
            # Workspace inspection
            "read_file": self.__handle_read_file,
            "list_dir": self.__handle_list_dir,
            "bulk_grep_search": self.__handle_grep_search,
            "diff_history": self.__handle_diff_history,
            # External information
            "web_search": self.__handle_web_search,
            # Report tools
            "generate_terraform_plan_report": self.__handle_report_plan_generator,
            "generate_terraform_drift_report": self.__handle_report_drift_generator,
            "generate_terraform_apply_report": self.__handle_report_apply_generator,
            # Domain tools
            "requests_filter": self.__handle_requests_filter,
            "construct_information": self.__handle_construct_information,
            "generate_terraform_targets": self.__handle_target_generator,
            "report_decomposed_task_operations": self.__handle_task_splitter,
            "task_complete": self.__handle_task_completion,
        }

    @override
    def get_available_tools(self, context: ToolContext) -> list[ToolDefinitionDTO]:
        """Get available tools for a specific context in LLM-compatible format"""
        filtered_tools: list[ToolDefinitionDTO] = []

        for _, tool_def in self.__tool_definitions.items():
            if tool_def.context == context:
                filtered_tools.append(tool_def)

        if not filtered_tools:
            raise ToolDefinitionContextNotFound(
                message=f"Tool definition not found for context={context}",
                error_code=404,
            )

        return filtered_tools

    @override
    def get_tool_definition(self, tool_name: str) -> ToolDefinitionDTO:
        """Get a specific tool definition by name in LLM-compatible format"""
        tool_def = self.__tool_definitions.get(tool_name)
        if not tool_def:
            raise ToolDefinitionNameNotFound(
                message=f"Tool definition name not found. got={tool_name}",
                error_code=404,
            )
        return tool_def

    @override
    async def execute_tool(self, tool_call: ToolCallDTO) -> ToolResultDTO:
        """Execute a tool call"""
        if tool_call.name not in self.__tool_handlers:
            return ToolResultDTO(
                name=tool_call.name,
                tool_call_id=tool_call.id,
                success=False,
                result=None,
                error_message=f"Tool {tool_call.name} not found",
            )

        try:
            handler = self.__tool_handlers[tool_call.name]
            if inspect.iscoroutinefunction(handler):
                result = await handler(tool_call.parameters)
            else:
                result = handler(tool_call.parameters)

            return ToolResultDTO(
                name=tool_call.name,
                tool_call_id=tool_call.id,
                success=True,
                result=result,
                error_message=None,
            )
        except ExceptionHandler as e:
            return ToolResultDTO(
                name=tool_call.name,
                tool_call_id=tool_call.id,
                success=False,
                result=None,
                error_message=e.message,
            )
        except Exception as e:
            logging.error(f"Tool {tool_call.name} failed: {e}")
            return ToolResultDTO(
                name=tool_call.name,
                tool_call_id=tool_call.id,
                success=False,
                result=None,
                error_message=str(e),
            )

    @override
    def validate_tool_parameters(
        self, tool_name: str, parameters: dict[str, Any]
    ) -> bool:
        """Validate tool parameters against the tool definition"""
        if tool_name not in self.__tool_definitions:
            return False

        tool_def = self.__tool_definitions[tool_name]
        required_params = tool_def.parameters.get("required", [])

        for param in required_params:
            if param not in parameters:
                logging.error(
                    f"Missing required parameter {param} for tool {tool_name}"
                )
                return False

        return True

    # Tool handlers
    def __handle_write_file(self, parameters: dict[str, Any]) -> str:
        target_file = parameters["target_file"]
        content = parameters["content"]

        if self.__filesystem.write_file(target_file, content):
            return f"Successfully wrote to {target_file}"
        return f"Failed to write to {target_file}"

    def __handle_replace_file(self, parameters: dict[str, Any]) -> str:
        target_file = parameters["target_file"]
        diff = parameters["diff"]

        if self.__filesystem.replace_in_file(target_file, diff):
            return f"Successfully replaced content in {target_file}"
        return f"Failed to replace content in {target_file}"

    def __handle_delete_file(self, parameters: dict[str, Any]) -> str:
        target_file = parameters["target_file"]

        if self.__filesystem.delete_file(target_file):
            return f"Successfully deleted {target_file}"
        return f"Failed to delete {target_file}"

    def __handle_read_file(self, parameters: dict[str, Any]) -> str:
        target_file = parameters["target_file"]

        content = self.__filesystem.read_file(target_file)
        return content

    def __handle_list_dir(self, parameters: dict[str, Any]) -> str:
        relative_path = parameters.get("relative_workspace_path", ".")

        contents = self.__filesystem.list_directory(relative_path)
        return "\n".join(contents)

    def __handle_grep_search(self, parameters: dict[str, Any]) -> str:
        results: list[list[str]] = []
        searches: list[dict[str, Any]] = parameters["searches"]

        for s in searches:
            query = s["query"]
            include_pattern = s.get("include_pattern")
            exclude_pattern = s.get("exclude_pattern")
            case_sensitive = s.get("case_sensitive", False)
            results.append(
                self.__filesystem.search_files(
                    query=query,
                    include_pattern=include_pattern,
                    exclude_pattern=exclude_pattern,
                    case_sensitive=case_sensitive,
                )
            )
        return "\n".join(["\n".join(r) for r in results])

    async def __handle_diff_history(self, parameters: dict[str, Any]) -> dict[str, str]:
        explanation = parameters["explanation"]
        result = await self.__git.show_diff()
        result += "\nUntracked changes:\n" + str(
            [
                f"{file}:\n"
                + self.__filesystem.read_file(
                    target_file=file,
                )
                for file in await self.__git.get_changed_files("A")
            ]
        )
        return {"diff": result, "explanation": explanation}

    async def __handle_web_search(self, parameters: dict[str, Any]) -> dict[str, str]:
        query = parameters["query"]
        explanation = parameters.get("explanation", "")
        return {
            "web_search": await self.__web_search.search(query),
            "explanation": explanation,
        }

    def __handle_target_generator(
        self, parameters: dict[str, Any]
    ) -> dict[str, list[str] | str]:
        targets = parameters["targets"]
        explanation = parameters.get("explanation", "")
        if not isinstance(targets, list):
            raise ToolInferenceParamsError(
                message=f"Target generation inference hasn't return the expected structure. got={targets}",
                error_code=500,
            )
        return {
            "targets": targets,
            "explanation": explanation,
        }

    def __handle_report_plan_generator(
        self, parameters: dict[str, Any]
    ) -> TerraformPlanReport:
        summary = parameters["summary"]
        changes = parameters["detailed_changes"]
        impact = parameters["potential_impact"]
        costs = parameters["estimated_costs"]
        return TerraformPlanReport(
            summary=summary,
            detailed_changes=changes,
            potential_impact=impact,
            estimated_costs=costs,
        )

    def __handle_report_drift_generator(
        self, parameters: dict[str, Any]
    ) -> TerraformDriftReport:
        summary = parameters["summary"]
        status = parameters["status"]
        resources = parameters["remediated_resources"]
        return TerraformDriftReport(
            summary=summary,
            status=status,
            remediated_resources=resources,
        )

    def __handle_report_apply_generator(
        self, parameters: dict[str, Any]
    ) -> TerraformApplyReport:
        summary = parameters["summary"]
        status = parameters["status"]
        execution_summary = parameters["execution_summary"]
        resource_changes = parameters["resource_changes"]
        recommendations = parameters["recommendations"]
        return TerraformApplyReport(
            summary=summary,
            status=status,
            execution_summary=execution_summary,
            resource_changes=resource_changes,
            recommendations=recommendations,
        )

    def __handle_requests_filter(
        self, parameters: dict[str, Any]
    ) -> dict[str, bool | str]:
        status = parameters["status"]
        explanation = parameters["explanation"]
        if not isinstance(status, bool):
            raise ToolInferenceParamsError(
                message=f"Requests filter inference hasn't return the expected structure. got={status}",
                error_code=500,
            )
        return {"status": status, "explanation": explanation}

    def __handle_construct_information(
        self, parameters: dict[str, Any]
    ) -> dict[str, str]:
        templates = parameters["templates"]
        abbreviations = parameters["abbreviations"]
        explanation = parameters.get("explanation", "")

        return {
            "templates": templates,
            "abbreviations": abbreviations,
            "explanation": explanation,
        }

    def __handle_task_completion(self, parameters: dict[str, Any]) -> dict[str, str]:
        status = parameters["status"]
        summary = parameters["summary"]

        return {
            "status": status,
            "summary": summary,
        }

    def __handle_task_splitter(
        self, parameters: dict[str, Any]
    ) -> dict[str, list[str] | str]:
        operations = parameters["operations"]
        explanation = parameters.get("explanation", "")
        if not isinstance(operations, list):
            raise ToolInferenceParamsError(
                message=f"Task Splitter inference hasn't return expected structure. got={operations}",
                error_code=500,
            )
        return {
            "operations": operations,
            "explanation": explanation,
        }
