# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
from typing import Any, Callable, override

from src.domains.interfaces import IFileSystem, IGit, ILLMProvider
from src.infrastructure.exceptions import (
    CustomFileNotFoundError,
    ToolInferenceParamsError,
)
from src.infrastructure.tools.tool_registry_static import ToolRegistryStatic
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
        super().__init__(llm)

    @override
    def _tool_files(self) -> dict[str, ToolContext]:
        return {
            "file_manipulation.json": ToolContext.FILE_OPERATIONS,
            "workspace_inspection.json": ToolContext.WORKSPACE_INSPECTION,
            **super()._tool_files(),
        }

    @override
    def _handlers(self) -> dict[str, Callable[[dict[str, Any]], Any]]:
        return {
            **super()._handlers(),
            # File operations
            "write_to_file": self.__handle_write_file,
            "replace_in_file": self.__handle_replace_file,
            "delete_file": self.__handle_delete_file,
            # Workspace inspection
            "read_file": self.__handle_read_file,
            "list_dir": self.__handle_list_dir,
            "bulk_grep_search": self.__handle_grep_search,
            "diff_history": self.__handle_diff_history,
        }

    def __handle_write_file(self, parameters: dict[str, Any]) -> dict[str, Any]:
        target_file = parameters["target_file"]
        content = parameters["content"]

        target_file = self.__limit_workspace_boundaries(target_file)

        self.__filesystem.write_file(target_file, content)
        return {
            "file": target_file,
        }

    def __handle_replace_file(self, parameters: dict[str, Any]) -> dict[str, Any]:
        target_file = parameters["target_file"]
        diff = parameters["diff"]

        target_file = self.__limit_workspace_boundaries(target_file)

        self.__filesystem.replace_in_file(target_file, diff)
        return {
            "file": target_file,
        }

    def __handle_delete_file(self, parameters: dict[str, Any]) -> dict[str, Any]:
        target_file = parameters["target_file"]

        target_file = self.__limit_workspace_boundaries(target_file)

        self.__filesystem.delete_file(target_file)
        return {
            "file": target_file,
        }

    def __handle_read_file(self, parameters: dict[str, Any]) -> dict[str, Any]:
        target_file = parameters["target_file"]

        target_file = self.__limit_workspace_boundaries(target_file)
        try:
            content = self.__filesystem.read_file(target_file)
        except CustomFileNotFoundError:
            raise ToolInferenceParamsError(
                message=f"{target_file} was not present in the authoritative "
                + "directory listing. Do not probe guessed filenames.",
                error_code=404,
            )
        return {
            "file": target_file,
            "content": content,
        }

    def __handle_list_dir(self, parameters: dict[str, Any]) -> dict[str, Any]:
        relative_path = self.__limit_workspace_boundaries(
            parameters["relative_workspace_path"]
        )

        items: list[Path] = sorted(self.__filesystem.list_directory(relative_path))
        return {
            "path": relative_path,
            "files": [i.name for i in items if i.is_file()],
            "directories": [i.name for i in items if i.is_dir()],
        }

    def __handle_grep_search(self, parameters: dict[str, Any]) -> list[dict[str, Any]]:
        MAX_GREP_MATCHES: int = 50
        searches: list[dict[str, Any]] = parameters["searches"]

        if not searches:
            raise ToolInferenceParamsError(
                message="Invalid request. At least one search is required.",
                error_code=400,
            )

        search_results: list[dict[str, Any]] = []
        for s in searches:
            query = s["query"]
            include_pattern = s.get("include_pattern")
            exclude_pattern = s.get("exclude_pattern")
            case_sensitive = s.get("case_sensitive", False)
            raw_matches: list[str] = self.__filesystem.search_files(
                query=query,
                include_pattern=include_pattern,
                exclude_pattern=exclude_pattern,
                case_sensitive=case_sensitive,
            )
            matches: list[str] = []
            workspace_path: str = str(self.__filesystem.project_root) + "/"
            for match in raw_matches:
                match = match.removeprefix(workspace_path)
                matches.append(match)
            search_results.append(
                {
                    "query": query,
                    "include_pattern": include_pattern,
                    "exclude_pattern": exclude_pattern,
                    "case_sensitive": case_sensitive,
                    "match_count": len(matches),
                    "truncated": len(matches) > MAX_GREP_MATCHES,
                    "matches": matches[:MAX_GREP_MATCHES],
                }
            )

        return search_results

    async def __handle_diff_history(self, parameters: dict[str, Any]) -> dict[str, Any]:
        result: list[str] = []
        diff = await self.__git.show_diff(working_tree=False, full_content=False)
        if diff:
            result.append(diff)
        untracked_files: list[str] = []
        for file in await self.__git.get_untracked_files():
            try:
                content = self.__filesystem.read_file(
                    self.__limit_workspace_boundaries(file)
                )
            except ExceptionHandler as e:
                logging.warning(f"Error reading file: {e.message}")
                continue
            if content:
                untracked_files.append(f"{file}:\n{content}")
        if untracked_files:
            result.append(untracked_files)

        return {
            "history_available": True,
            "changes": result,
        }

    def __limit_workspace_boundaries(self, path: str) -> str:
        """Normalize a tool path to one relative to the working directory.

        Absolute paths are accepted when they point inside the working
        directory; anything resolving outside of it, or into an entry
        Kumoss manages (git metadata, backend override), is rejected.
        """
        root: Path = self.__filesystem.project_root.resolve()
        resolved: Path = (root / path).resolve()
        if not resolved.is_relative_to(root):
            raise ToolInferenceParamsError(
                message=f"Path '{path}' is outside the working directory '{root}'. "
                + "Only files inside the working directory are accessible; "
                + "use paths relative to it (e.g. 'main.tf', '.').",
                error_code=400,
            )
        relative = resolved.relative_to(root)
        if self.__filesystem.protected_names.intersection(relative.parts):
            raise ToolInferenceParamsError(
                message=f"Path '{path}' is managed by Kumoss and is not accessible.",
                error_code=403,
            )
        return relative.as_posix()
