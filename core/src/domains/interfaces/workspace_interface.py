# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod
from pathlib import Path
from uuid import UUID


class IWorkspace(ABC):
    """Per-call git workspace lifecycle.

    A workspace is a directory at {base}/{session_id}/{call_id}/ that
    exists only for the duration of one use-case call. On success the
    branch is pushed to origin and the directory is removed; on failure
    the directory is removed unchanged.

    A session additionally owns one pinned slot at
    {base}/{session_id}/pinned/: the workspace of the last successful
    generate/drift round, promoted (renamed) there at round end so its
    validated plan artifact can be applied by a later apply call.
    """

    @abstractmethod
    async def validate_uri(self, repo_uri: str) -> None:
        """Verify the URI is reachable. Raises InvalidRepoURI on failure."""

    @abstractmethod
    async def setup_call_dir(
        self,
        session_id: UUID,
        repo_uri: str,
        branch: str,
    ) -> Path:
        """Shallow-clone into the per-call directory. Returns the dir path."""

    @abstractmethod
    def iac_root(self, call_dir: Path, iac_path: str | None) -> Path:
        """Resolve the IaC root of a call directory.

        Symlinks are resolved: the root must be an existing directory
        inside ``call_dir``, so a committed link cannot widen the scope
        of the tools working in it. Raises InvalidIacPath otherwise.
        """

    @abstractmethod
    def cleanup(self, call_dir: Path) -> None:
        """Remove the per-call directory. Idempotent."""

    @abstractmethod
    def pinned_dir(self, session_id: UUID) -> Path:
        """Path of the session's pinned workspace slot (may not exist)."""

    @abstractmethod
    def pin_workspace(self, session_id: UUID, call_dir: Path) -> None:
        """Promote a validated workspace into the pinned slot.

        Renames ``call_dir`` to the pinned slot, replacing any previous
        pin — latest successful round wins. The workspace must already
        contain the plan artifact and its initialized ``.terraform``
        directory; that is what makes the later apply possible without
        re-running init or plan.
        """

    @abstractmethod
    def discard_pinned(self, session_id: UUID) -> None:
        """Remove the session's pinned slot. Idempotent."""

    @abstractmethod
    def pinned_plan_path(self, session_id: UUID) -> Path | None:
        """Path of the session's single pinned plan artifact, or None.

        A session pins at most one plan. The artifact is located
        inside the pinned slot.
        """
