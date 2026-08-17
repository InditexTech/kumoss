# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.dto import PullRequestDTO, ToolResultDTO
from src.domains.entities import SessionContext
from src.domains.interfaces.git_interface import IGit
from src.domains.services import TemplateOrchestrationService, ToolOrchestrationService
from src.domains.services.database_service import DatabaseService
from src.domains.services.llm_service import LLMOrchestrationService
from src.shared.constants import PromptsLibrary, ToolContext


class PullRequestService:
    def __init__(
        self,
        session_ctx: SessionContext | None,
        git_utils: IGit,
        llm_service: LLMOrchestrationService,
        tool_service: ToolOrchestrationService,
        template_service: TemplateOrchestrationService,
    ):
        self.__ctx = session_ctx
        self.__git_utils = git_utils
        self.__llm_svc = llm_service
        self.__tool_svc = tool_service
        self.__template_svc = template_service

    async def create_pr(self) -> PullRequestDTO:
        assert self.__ctx is not None
        response: ToolResultDTO = await self.__llm_svc.generate(
            query="Create a pull request from this IaC session.",
            tools=[self.__tool_svc.get_sentinel_tool(ToolContext.PR_GENERATOR)],
            prompt=await self.__template_svc.render(
                PromptsLibrary.PR_GENERATOR, operation_type=self.__ctx.operation
            ),
            history=self.__ctx.history,
        )
        if not response.success or not isinstance(response.result, dict):
            raise RuntimeError(
                f"PR generation failed: {response.error_message or response.result}"
            )

        title = response.result.get("title")
        description = response.result.get("description")
        if not isinstance(title, str) or not isinstance(description, str):
            raise RuntimeError(
                f"PR generation returned invalid payload: {response.result}"
            )

        dto = await self.__git_utils.create_pr(
            repository_url=self.__ctx.repo_uri,
            head_branch=self.__ctx.branch_name,
            title=title,
            description=description,
        )
        await DatabaseService.add_pull_request(self.__ctx.id, dto.url)
        return dto
