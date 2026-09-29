# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import json
import inspect
from pathlib import Path
from typing import Any, Callable, override

from pydantic import ValidationError

from src.domains.interfaces import ILLMProvider, IToolRegistry
from src.domains.dto import (
    ComplianceCheckReport,
    TerraformDriftReport,
    ToolCallDTO,
    ToolResultDTO,
    ToolDefinitionDTO,
    TerraformPlanReport,
    TerraformApplyReport,
    TerraformImportReport,
)
from src.infrastructure.exceptions import (
    InferenceCallAPIError,
    InferenceCallWebSearchNotSupported,
    ToolDefinitionContextNotFound,
    ToolDefinitionNameNotFound,
    ToolInferenceParamsError,
)
from src.shared.constants import ToolContext
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging


class ToolRegistryStatic(IToolRegistry):
    def __init__(self, llm: ILLMProvider):
        self.__llm = llm
        self.__tools_directory = Path(__file__).parent
        self.__tool_definitions: dict[str, ToolDefinitionDTO] = {}
        self.__tool_handlers: dict[str, Callable[[dict[str, Any]], Any]] = (
            self._handlers()
        )
        self.__load_tools()

    def _tool_files(self) -> dict[str, ToolContext]:
        """Map JSON definition files to their tool context. Subclasses extend."""
        return {
            "requests_filter.json": ToolContext.REQUESTS_FILTER,
            "task_splitter.json": ToolContext.TASK_SPLITTER,
            "prompt_compositor.json": ToolContext.PROMPT_COMPOSITOR,
            "target_generator.json": ToolContext.TARGET_GENERATOR,
            "report_generator.json": ToolContext.REPORT_GENERATOR,
            "pr_generator.json": ToolContext.PR_GENERATOR,
            "external_information.json": ToolContext.EXTERNAL_INFORMATION,
            "task_completion.json": ToolContext.GENERAL_TASK_COMPLETION,
            "iac_import.json": ToolContext.IMPORT_ADDRESSES,
            "compliance_checker.json": ToolContext.COMPLIANCE_CHECK,
        }

    def __load_tools(self):
        """Load tool definitions from JSON files"""
        for filename, context in self._tool_files().items():
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

    def _handlers(self) -> dict[str, Callable[[dict[str, Any]], Any]]:
        """Map tool names to execution handlers. Subclasses extend."""
        return {
            # Report tools
            "generate_terraform_plan_report": self.__handle_report_plan_generator,
            "generate_terraform_drift_report": self.__handle_report_drift_generator,
            "generate_terraform_apply_report": self.__handle_report_apply_generator,
            "generate_terraform_import_report": self.__handle_report_import_generator,
            # Domain tools
            "requests_filter": self.__handle_requests_filter,
            "generate_pull_request": self.__handle_pr_generator,
            "construct_information": self.__handle_construct_information,
            "generate_terraform_targets": self.__handle_target_generator,
            "report_decomposed_task_operations": self.__handle_task_splitter,
            "task_complete": self.__handle_task_completion,
            "import_addresses": self.__handle_import_addresses,
            "report_compliance_findings": self._handle_compliance_findings,
            # External information
            "web_search": self.__handle_web_search,
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

    def __handle_target_generator(
        self, parameters: dict[str, Any]
    ) -> dict[str, list[str] | str]:
        targets = parameters["targets"]
        explanation = parameters.get("explanation", "")
        if not isinstance(targets, list):
            raise ToolInferenceParamsError(
                message=f"Target generation inference hasn't returned the expected structure. got={targets}",
                error_code=400,
            )
        return {
            "targets": targets,
            "explanation": explanation,
        }

    def __handle_report_plan_generator(
        self, parameters: dict[str, Any]
    ) -> TerraformPlanReport | str:
        summary = parameters["summary"]
        changes = parameters["detailed_changes"]
        impact = parameters["potential_impact"]
        costs = parameters["estimated_costs"]
        try:
            return TerraformPlanReport(
                summary=summary,
                detailed_changes=changes,
                potential_impact=impact,
                estimated_costs=costs,
            )
        except ValidationError as e:
            raise ToolInferenceParamsError(
                message=e.json(),
                error_code=400,
            )

    def __handle_report_drift_generator(
        self, parameters: dict[str, Any]
    ) -> TerraformDriftReport:
        summary = parameters["summary"]
        status = parameters["status"]
        resources = parameters["remediated_resources"]
        try:
            return TerraformDriftReport(
                summary=summary,
                status=status,
                remediated_resources=resources,
                unreconciled_drift=parameters.get("unreconciled_drift", []),
                whitelisted_exceptions=parameters.get("whitelisted_exceptions", []),
            )
        except ValidationError as e:
            raise ToolInferenceParamsError(
                message=e.json(),
                error_code=400,
            )

    def __handle_report_apply_generator(
        self, parameters: dict[str, Any]
    ) -> TerraformApplyReport:
        summary = parameters["summary"]
        status = parameters["status"]
        execution_summary = parameters["execution_summary"]
        resource_changes = parameters["resource_changes"]
        recommendations = parameters["recommendations"]
        try:
            return TerraformApplyReport(
                summary=summary,
                status=status,
                execution_summary=execution_summary,
                resource_changes=resource_changes,
                recommendations=recommendations,
            )
        except ValidationError as e:
            raise ToolInferenceParamsError(
                message=e.json(),
                error_code=400,
            )

    def __handle_report_import_generator(
        self, parameters: dict[str, Any]
    ) -> TerraformImportReport:
        summary = parameters["summary"]
        status = parameters["status"]
        execution_summary = parameters["execution_summary"]
        imported_resources = parameters["imported_resources"]
        excluded_resources = parameters["excluded_resources"]
        state_alignment = parameters["state_alignment"]
        recommendations = parameters["recommendations"]
        try:
            return TerraformImportReport(
                summary=summary,
                status=status,
                execution_summary=execution_summary,
                imported_resources=imported_resources,
                excluded_resources=excluded_resources,
                state_alignment=state_alignment,
                recommendations=recommendations,
            )
        except ValidationError as e:
            raise ToolInferenceParamsError(
                message=e.json(),
                error_code=500,
            )

    def __handle_requests_filter(
        self, parameters: dict[str, Any]
    ) -> dict[str, bool | str]:
        status = parameters["status"]
        explanation = parameters["explanation"]
        if not isinstance(status, bool):
            raise ToolInferenceParamsError(
                message=f"Requests filter inference hasn't returned the expected structure. got={status}",
                error_code=400,
            )
        return {"status": status, "explanation": explanation}

    def __handle_pr_generator(self, parameters: dict[str, Any]) -> dict[str, str]:
        title = parameters.get("title")
        description = parameters.get("description")
        if not isinstance(title, str) or not isinstance(description, str):
            raise ToolInferenceParamsError(
                message="PR generation inference hasn't returned the expected structure."
                + f" got={parameters}",
                error_code=400,
            )
        return {"title": title, "description": description}

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
                message=f"Task Splitter inference hasn't returned the expected structure. got={operations}",
                error_code=400,
            )
        return {
            "operations": operations,
            "explanation": explanation,
        }

    def __handle_import_addresses(self, parameters: dict[str, Any]) -> dict[str, Any]:
        status = parameters["status"]
        summary = parameters["summary"]
        imports = parameters["imports"]
        if not isinstance(imports, list):
            raise ToolInferenceParamsError(
                message=f"IAC import inference hasn't returned the expected structure. got={imports}",
                error_code=500,
            )
        return {"status": status, "summary": summary, "imports": imports}

    async def __handle_web_search(self, parameters: dict[str, Any]) -> str:
        query = parameters["query"]
        try:
            response = await self.__llm.inference(msg=query, web_search=True)
        except (
            InferenceCallWebSearchNotSupported,
            InferenceCallAPIError,
        ) as e:
            return f"Web search is unavailable: {e.message}. Do NOT retry web_search."

        if not response.text:
            return f"Web search with query '{query}' returned no content. Do NOT retry web_search."
        return response.text

    def _handle_compliance_findings(
        self, parameters: dict[str, Any]
    ) -> ComplianceCheckReport:
        try:
            violations = parameters["violations"]
            return ComplianceCheckReport(
                passed=not any(
                    violation["severity"] in {"error", "critical"}
                    for violation in violations
                ),
                violations=violations,
                summary=parameters["summary"],
                checked_rules=parameters["checked_rules"],
            )
        except ValidationError as e:
            raise ToolInferenceParamsError(
                message=e.json(),
                error_code=400,
            )
