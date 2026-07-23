# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.dto import PullRequestDTO
from src.domains.entities import SessionContext
from src.domains.interfaces.git_interface import IGit
from src.domains.services.database_service import DatabaseService
from src.domains.services.llm_service import LLMOrchestrationService


class PullRequestService:
    def __init__(
        self,
        git_utils: IGit,
        llm_service: LLMOrchestrationService,
    ):
        self.__llm_svc = llm_service
        self.__git_utils = git_utils

    async def create_pr(self, ctx: SessionContext) -> PullRequestDTO:
        await DatabaseService.add_pull_request(ctx.id, ctx.repo_uri)
        return await self.__git_utils.create_pr(
            repository_url=ctx.repo_uri,
            head_branch=ctx.branch_name,
            title="TODO",
            # title=session.history.get_first_turn.user, # session history property getter
            description=await self.__llm_svc.generate_text(
                "transform the following data into markdown format"
                + f" for a PR description: {ctx}"  # TODO: get artifact
            ),
        )
