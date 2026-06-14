# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod
from pathlib import Path
from uuid import UUID


class IWorkspace(ABC):
    """Per-call git workspace lifecycle.

    A workspace is a directory at {base}/sessions/{session_id}/{call_id}/
    that exists only for the duration of one use-case call. On success the
    branch is pushed to origin and the directory is removed; on failure the
    directory is removed unchanged.
    """

    @abstractmethod
    async def validate_uri(self, repo_uri: str) -> None:
        """Verify the URI is reachable. Raises InvalidRepoURI on failure."""

    @abstractmethod
    async def setup_call_dir(
        self,
        *,
        session_id: UUID,
        call_id: UUID,
        repo_uri: str,
        branch: str | None,
        create_branch: bool = False,
    ) -> Path:
        """Shallow-clone into the per-call directory. Returns the dir path."""

    @abstractmethod
    async def push_and_cleanup(self, *, call_dir: Path, branch: str) -> None:
        """Push the branch to origin and remove the per-call directory."""

    @abstractmethod
    def cleanup(self, call_dir: Path) -> None:
        """Remove the per-call directory. Idempotent."""
