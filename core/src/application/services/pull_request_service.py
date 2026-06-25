# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.dto import PullRequestDTO
from src.domains.interfaces.git_interface import IGit
from src.domains.services.llm_service import LLMOrchestrationService
from src.infrastructure.database.models import UserSession


class PullRequestService:
    def __init__(
        self,
        git_utils: IGit,
        llm_service: LLMOrchestrationService,
    ):
        self.__llm_svc = llm_service
        self.__git_utils = git_utils

    async def create_pr(self, session: UserSession) -> PullRequestDTO:
        return await self.__git_utils.create_pr(
            repository_url=session.repo_uri,
            head_branch=session.branch_name,
            title="TODO",
            # title=session.history.get_first_turn.user, # session history property getter
            description=await self.__llm_svc.generate_text(
                "transform the following data into makdown format"
                + f" for a PR descrition: {session.last_payload}"
            ),
        )
