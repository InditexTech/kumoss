# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Any, Callable, override

from src.domains.dto import ComplianceCheckReport, ComplianceContextDTO
from src.domains.interfaces import IFileSystem, IGit, ILLMProvider
from src.infrastructure.exceptions import ToolInferenceParamsError
from src.infrastructure.tools.tool_registry_static import ToolRegistryStatic
from src.shared.config import system_config
from src.shared.constants import ToolContext
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging


class ToolRegistryWorkspace(ToolRegistryStatic):
    def __init__(
        self,
        filesystem: IFileSystem,
        git: IGit,
        llm: ILLMProvider,
    ):
        self.__filesystem = filesystem
        self.__git = git
        self.__llm = llm
        self.__compliance_checker = None
        self.__compliance_passed = False
        self.__compliance_check_count = 0
        self.__chain_history = None
        super().__init__(llm)

    def set_compliance_checker(self, checker) -> None:
        self.__compliance_checker = checker

    def set_chain_history(self, history) -> None:
        self.__chain_history = history

    @override
    def _tool_files(self) -> dict[str, ToolContext]:
        return {
            "file_manipulation.json": ToolContext.FILE_OPERATIONS,
            "workspace_inspection.json": ToolContext.WORKSPACE_INSPECTION,
            "inline_compliance.json": ToolContext.INLINE_COMPLIANCE,
            **super()._tool_files(),
        }

    @override
    def _handlers(self) -> dict[str, Callable[[dict[str, Any]], Any]]:
        base = super()._handlers()
        base["task_complete"] = self.__handle_task_completion_gated
        return {
            **base,
            # File operations
            "write_to_file": self.__handle_write_file,
            "replace_in_file": self.__handle_replace_file,
            "delete_file": self.__handle_delete_file,
            # Workspace inspection
            "read_file": self.__handle_read_file,
            "list_dir": self.__handle_list_dir,
            "bulk_grep_search": self.__handle_grep_search,
            "diff_history": self.__handle_diff_history,
            # Compliance
            "check_compliance": self.__handle_check_compliance,
        }

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

    async def __handle_diff_history(self, parameters: dict[str, Any]) -> str:
        result = await self.__git.show_diff(working_tree=False, full_content=False)
        untracked_files: list[str] = []
        for file in await self.__git.get_untracked_files():
            try:
                content = self.__filesystem.read_file(file)
            except ExceptionHandler as e:
                logging.warning(f"Error reading file: {e.message}")
                continue
            untracked_files.append(f"{file}:\n{content}")
        result += "\nUntracked changes:\n" + "\n".join(untracked_files)
        return result

    def __handle_task_completion_gated(
        self, parameters: dict[str, Any]
    ) -> dict[str, str]:
        if (
            self.__compliance_checker is not None
            and system_config.compliance.enabled
            and not self.__compliance_passed
        ):
            raise ToolInferenceParamsError(
                message="Cannot complete: compliance check has not passed. "
                "Call check_compliance first and resolve all violations.",
                error_code=400,
            )
        status = parameters["status"]
        summary = parameters["summary"]
        return {"status": status, "summary": summary}

    async def __handle_check_compliance(
        self, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        if self.__compliance_checker is None:
            return ComplianceCheckReport(
                passed=True,
                violations=[],
                summary="Compliance checker not configured",
                checked_rules=[],
            ).model_dump()

        self.__compliance_check_count += 1
        if self.__compliance_check_count > system_config.compliance.max_retries:
            if system_config.compliance.auto_pass_on_max_retries:
                logging.warning("Compliance check max retries exceeded, auto-passing")
                self.__compliance_passed = True
                return ComplianceCheckReport(
                    passed=True,
                    violations=[],
                    summary="Max compliance retries exceeded, auto-passed.",
                    checked_rules=[],
                ).model_dump()
            logging.warning("Compliance check max retries exceeded, blocking")
            return ComplianceCheckReport(
                passed=False,
                violations=[],
                summary="Max compliance retries exceeded.",
                checked_rules=[],
            ).model_dump()

        history = self.__chain_history.serialize() if self.__chain_history else None
        context = ComplianceContextDTO(history=history) if history else None
        report = await self.__compliance_checker.check(context=context)
        self.__compliance_passed = report.passed
        return report.model_dump()
