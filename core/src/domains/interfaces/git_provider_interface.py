# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod

from src.domains.dto import PullRequestDTO


class IGitProvider(ABC):
    @abstractmethod
    async def create_pr(
        self,
        owner: str,
        repository: str,
        head: str,
        base: str,
        title: str,
        description: str,
    ) -> PullRequestDTO:
        """Create a Pull Request

        Args:
            owner: The account owner of the repository.
            repository: The name of the repository without the .git extension.
            head: The name of the branch where your changes are implemented.
            base: The name of the branch you want the changes pulled into.
            title: The title of the new pull request.
            description: The contents of the pull request.

        Returns:
            A PullRequestDTO object
        """
        pass

    @abstractmethod
    async def complete_pr(self, owner: str, repository: str, id: int) -> None:
        """Complete or accept a Pull Request ID"""
        pass
