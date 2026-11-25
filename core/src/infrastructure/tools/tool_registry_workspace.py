# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
from typing import Any, Callable, override

from src.domains.interfaces import IFileSystem, IGit
from src.domains.value_objects import SearchResult, TerraformDoc
from src.infrastructure.exceptions import (
    CustomFileNotFoundError,
    SearchEngineError,
    TerraformDocsNotFoundError,
    TerraformRegistryError,
    ToolInferenceParamsError,
)
from src.infrastructure.external.search_service import SearchServiceClient
from src.infrastructure.external.search_summarizer_service import (
    SearchResultsSummarizer,
)
from src.infrastructure.external.terraform_registry_service import (
    TerraformRegistryClient,
)
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
        summarizer: SearchResultsSummarizer,
    ):
        self.__summarizer = summarizer
        self.__filesystem = filesystem
        self.__git = git
        super().__init__()

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
            # External information
            "web_search": self.__handle_web_search,
            "terraform_docs": self.__handle_terraform_docs,
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

    async def __handle_web_search(self, parameters: dict[str, Any]) -> dict[str, Any]:
        query = parameters["query"]
        if not system_config.web_search.provider:
            return {
                "query": query,
                "result": "Web search is unavailable: no provider configured. Do NOT retry web_search.",
            }
        try:
            results = await SearchServiceClient().search(query)
        except SearchEngineError as e:
            return {
                "query": query,
                "result": f"Web search is unavailable: {e.message}. Do NOT retry web_search.",
            }
        if not results:
            return self.__no_results(
                query, f"Web search with query '{query}' returned no content."
            )
        summaries = await self.__summarized_search_results(query, results)
        if summaries is None:
            return self.__no_results(
                query,
                f"Web search with query '{query}' returned no relevant content.",
            )
        return {"query": query, "result": summaries}

    def __no_results(self, query: str, reason: str) -> dict[str, Any]:
        """Answer a search that found nothing with a nudge to rephrase.

        The retry budget is the agent loop's own
        (``orchestration.max_tool_agent_executions``); this tool only
        reports what happened and asks for a better query. Only
        query-shaped failures come through here — a missing provider or a
        broken engine answers immediately, since no rephrasing fixes
        either.
        """
        return {
            "query": query,
            "result": (
                f"{reason} Search again with a different query — other "
                + "keywords, synonyms, or a broader or narrower scope. Do "
                + "not repeat this query."
            ),
        }

    async def __summarized_search_results(
        self, query: str, results: list[SearchResult]
    ) -> str | None:
        """Condense every hit, rank them, return the top summaries.

        ``None`` means the pages were read and none answers the query,
        which the caller turns into a dead end. Every summarizer
        *failure* instead degrades to the raw, unfiltered results, so
        the tool call never fails on account of the reduction.
        """
        try:
            selected, discarded = await self.__summarizer.best(query, results)
        except Exception as e:
            logging.warning(
                f"Search result summarization failed, returning raw results: {e!r}"
            )
            return "\n".join(f"- {r.title}: {r.content} ({r.url})" for r in results)
        if not selected:
            logging.debug(
                f"web_search '{query}' found no relevant page among "
                + f"{len(results)} result(s)."
            )
            return None
        if discarded:
            logging.debug(
                "web_search '"
                + query
                + "' discarded "
                + str(len(discarded))
                + " source(s) considered less relevant: "
                + "; ".join(f"{s.result.title} ({s.result.url})" for s in discarded)
            )
        return "\n".join(
            f"- {s.result.title}: {s.summary} ({s.result.url})" for s in selected
        )

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

    async def __handle_terraform_docs(
        self, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        provider = parameters["provider"]
        resource_type = parameters["resource_type"]
        focus = parameters["focus"]
        version = parameters.get("version") or None
        section = parameters.get("section") or "full"
        kind = parameters.get("kind") or "resource"
        if section not in ("full", "import") or kind not in ("resource", "data_source"):
            raise ToolInferenceParamsError(
                message="`section` must be 'full' or 'import' and `kind` must be "
                + f"'resource' or 'data_source'. got section={section}, kind={kind}",
                error_code=400,
            )
        if section == "import" and kind == "data_source":
            raise ToolInferenceParamsError(
                message="Data sources cannot be imported and have no Import "
                + "section; use section 'full' for a data source.",
                error_code=400,
            )
        if not isinstance(focus, str) or not focus.strip():
            raise ToolInferenceParamsError(
                message="`focus` must say what you need from the documentation.",
                error_code=400,
            )
        answer: dict[str, Any] = {
            "provider": provider,
            "version": version,
            "resource_type": resource_type,
            "section": section,
        }
        try:
            doc = await TerraformRegistryClient().fetch(
                provider, resource_type, version, data_source=kind == "data_source"
            )
        except TerraformDocsNotFoundError as e:
            return answer | {
                "result": f"{e.message} Check the provider source, version and "
                + "type name before calling terraform_docs again; do not repeat "
                + "this call."
            }
        except TerraformRegistryError as e:
            return answer | {
                "result": f"Terraform documentation is unavailable: {e.message}. "
                + "Do NOT retry terraform_docs; use web_search instead."
            }
        answer |= {"provider": doc.source, "version": doc.version, "url": doc.url}
        content = doc.content
        if section == "import":
            content = TerraformRegistryClient.import_section(doc.content)
            if content is None:
                return answer | {
                    "result": f"The documentation of {doc.resource_type} in "
                    + f"{doc.source} {doc.version} has no Import section: the "
                    + "resource type may not support import."
                }
        return answer | {
            "result": await self.__condensed_docs(doc, content, focus.strip())
        }

    async def __condensed_docs(
        self, doc: TerraformDoc, content: str, focus: str
    ) -> str:
        """``content`` of the page condensed to ``focus`` by the search summarizer.

        A page is one resource's own documentation, so there is nothing
        to rank: only the per-page summary runs. Any summarizer failure
        degrades to the raw, truncated content, as for ``web_search``.
        """
        content = content[: TerraformRegistryClient.MAX_DOC_CHARS]
        page = SearchResult(
            title=f"{doc.resource_type} ({doc.source} {doc.version})",
            url=doc.url,
            content=content,
        )
        try:
            summary = await self.__summarizer.condense(
                f"{doc.resource_type}: {focus}", page
            )
        except ExceptionHandler as e:
            logging.warning(
                f"Terraform docs summarization failed, returning the raw page: {e!r}"
            )
            return content
        if summary is None:
            return (
                f"The documentation of {doc.resource_type} in {doc.source} "
                + f"{doc.version} has nothing on '{focus}'. Ask with a different "
                + "focus; do not repeat this one."
            )
        return summary
