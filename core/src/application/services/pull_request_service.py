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
        session_ctx: SessionContext,
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
        response: ToolResultDTO = await self.__llm_svc.generate(
            query="I need you to create PR",
            tools=self.__tool_svc.get_available_tools(
                contexts=[ToolContext.WORKSPACE_INSPECTION]
            ),
            sentinel_tool=self.__tool_svc.get_sentinel_tool(ToolContext.PR_GENERATOR),
            prompt=await self.__template_svc.render(
                PromptsLibrary.PR_GENERATOR, operation_type=self.__ctx.operation
            ),
            history=self.__ctx.history,
        )
        result: dict[str, str] = response.result
        dto = await self.__git_utils.create_pr(
            repository_url=self.__ctx.repo_uri,
            head_branch=self.__ctx.branch_name,
            title=result["title"],
            description=result["description"],
        )
        await DatabaseService.add_pull_request(self.__ctx.id, dto.url)
        return dto

    async def merge(self, url: str, pr_id: int) -> None:
        await self.__git_utils.complete_pr(url, pr_id)
