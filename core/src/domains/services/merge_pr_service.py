# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.interfaces.git_interface import IGit
from src.domains.services.database_service import DatabaseService
from src.shared.exceptions import ExceptionHandler


class MergePullRequestService:
    """Looks up a session and merges the associated pull request."""

    def __init__(self, git: IGit):
        self.__git = git

    async def merge(self, session_id: str, pr_id: int) -> None:
        session = await DatabaseService.get_session(session_id)
        if not session:
            raise ExceptionHandler(f"Session {session_id} not found.", 404)
        await self.__git.complete_pr(session.repo_uri, pr_id)
