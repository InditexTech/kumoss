# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Literal
from abc import ABC, abstractmethod

from src.domains.dto import PullRequestDTO


class IGit(ABC):
    @property
    @abstractmethod
    def error_msg(self) -> str:
        pass

    @abstractmethod
    async def ls_remote(self, *git_options: str) -> bool:
        """Return True if the remote URI is reachable, False otherwise.

        ``git_options`` go between ``git`` and ``ls-remote`` (e.g. ``-c k=v``).
        """
        pass

    @abstractmethod
    async def clone_repository(
        self,
        repo_url: str,
        repository_name: str,
        *extra_args: str,
        timeout: int = 300,
    ) -> bool:
        """Clone the repository at ``repo_url`` into ``repository_name``.

        ``branch`` is optional; when ``None``, the cloner uses the remote's
        default branch. When ``create_branch`` is True and ``branch`` is provided, the clone
        uses the default branch and then creates a new local branch.

        ``extra_args`` are passed through verbatim to ``git clone``.
        Use for optional flags that control the shape of the clone without
        adding a dedicated method — for example ``--filter=blob:none`` to
        skip fetching file blobs (partial clone) or ``--no-checkout`` to skip
        populating the working tree.  These arguments are injected between
        the built-in flags (``--depth``, ``--branch``) and the trailing
        ``<repo> <dir>`` positionals.

        ``timeout`` is the maximum seconds to wait for the clone subprocess.
        """
        pass

    @abstractmethod
    async def push_branch(self, branch: str) -> bool:
        """Push ``branch`` to origin with upstream tracking. Returns True on success."""
        pass

    @abstractmethod
    async def checkout(self, branch: str) -> None:
        pass

    @abstractmethod
    async def commit_and_push(self, branch: str) -> None:
        pass

    @abstractmethod
    async def create_pr(
        self,
        repository_url: str,
        head_branch: str,
        title: str,
        description: str,
    ) -> PullRequestDTO:
        """Create a Pull Request

        Args:
            repository_url: The full repository URL.
            head_branch: The branch where the changes are implemented.
            title: The PR title.
            description: The PR description.
        """
        pass

    @abstractmethod
    async def complete_pr(self, pr_id: int) -> None:
        pass

    @abstractmethod
    async def get_default_branch(self) -> str:
        pass

    @abstractmethod
    async def get_workspace_revision(self) -> str:
        """Return a fingerprint of the working tree's current revision.

        Covers both the checked-out commit and any uncommitted or untracked
        change on top of it, so two equal fingerprints mean the tree holds
        the same code.
        """
        pass

    @abstractmethod
    async def get_untracked_files(self) -> list[str]:
        """get_untracked_files returns a list of file names that are not tracked by git and
        are not ignored by standard excludes (e.g. .gitignore)."""
        pass

    @abstractmethod
    async def get_changed_files(
        self,
        working_tree: bool,
        diff_filter: Literal["A", "M", "D", "AMD"],
    ) -> list[str]:
        """This function return a list of files that has been modified or created
        based on the given filter.

        Args:
            working_tree: Whether the output only includes unstaged changes in the working tree.
            diff_filter: A - added | M - modified | D - deleted
        """
        pass

    @abstractmethod
    async def show_diff(
        self,
        working_tree: bool,
        full_content: bool,
        file_path: str = None,
    ) -> str:
        """show_diff returns a plain text string containing the diff for files tracked by git.STAGED and COMMITED files
        SINCE the current branch diverged from the default branch

        Args:
            wroking_tree: Whether the output only includes unstaged changes in the working tree.
            full_content: Unify all the content lines - not just the changed ones.
        """
        pass
