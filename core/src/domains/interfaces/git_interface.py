# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Literal
from abc import ABC, abstractmethod

from src.domains.dto import PullRequestDTO


class IGit(ABC):
    @property
    @abstractmethod
    def branch(self) -> str:
        pass

    @property
    @abstractmethod
    def error_msg(self) -> str:
        pass

    @abstractmethod
    async def ls_remote(self, repo_uri: str) -> bool:
        """Return True if the remote URI is reachable, False otherwise."""
        pass

    @abstractmethod
    async def clone_repository(
        self,
        repo_url: str,
        repository_name: str,
        branch: str | None = None,
        depth: int | None = None,
        create_branch: bool = False,
    ) -> bool:
        """Clone the repository at ``repo_url`` into ``repository_name``.

        ``branch`` is optional; when ``None``, the cloner uses the remote's
        default branch. ``depth`` limits commit history (shallow clone).
        When ``create_branch`` is True and ``branch`` is provided, the clone
        uses the default branch and then creates a new local branch.
        """
        pass

    @abstractmethod
    async def push_branch(self, branch: str) -> bool:
        """Push ``branch`` to origin with upstream tracking. Returns True on success."""
        pass

    @abstractmethod
    async def checkout(self) -> None:
        pass

    @abstractmethod
    async def commit(self) -> None:
        pass

    @abstractmethod
    async def create_pr(
        self,
        description: str,
        repository_name: str,
        target_branch: str,
    ) -> PullRequestDTO:
        pass

    @abstractmethod
    async def complete_pr(self, pr_id: int) -> bool:
        pass

    @abstractmethod
    async def get_remote_url(self) -> str:
        pass

    @abstractmethod
    async def get_default_branch(self) -> str:
        pass

    @abstractmethod
    async def get_changed_files(
        self, diff_filter: Literal["A", "M", "AM"]
    ) -> list[str]:
        """This function return a list of files that has been modified or created
        since the current branch has been created based on the given filter.
        A: added
        M: modified
        """
        pass

    @abstractmethod
    async def show_diff(self) -> str:
        """show_diff returns a plain text string containing the diff for all the STAGED and COMMITED files
        SINCE the current branch diverged from the default branch
        """
        pass
