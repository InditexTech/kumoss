# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import shutil
import tempfile
from pathlib import Path
from typing import ClassVar, final, override
from uuid import UUID
from uuid import uuid4

from src.domains.interfaces.workspace_interface import IWorkspace
from src.infrastructure.exceptions import GitError, InvalidRepoURI
from src.infrastructure.filesystem.file_system import FileSystemUtils
from src.infrastructure.filesystem.git.git_utils import GitUtils
from src.infrastructure.filesystem.git.repo_uri_guard import (
    REJECTED_MESSAGE,
    ensure_repo_uri_allowed,
)
from src.shared.config import system_config
from src.shared.logger import logging


@final
class WorkspaceService(IWorkspace):
    """Implements IWorkspace using GitUtils for git ops and shutil for filesystem ops."""

    _REUSE_MARKER: ClassVar[str] = "INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)"

    def __init__(self, base_path: Path | None = None):
        self._override_base = base_path

    @property
    def _base(self) -> Path:
        return self._override_base or system_config.paths.upload_folder

    def __add_terraform_gitignore(self, path: Path) -> bool:
        utils = FileSystemUtils(path)
        with open(Path(__file__).resolve().parent / "terraform.gitignore", "r") as f:
            content = f.read()
        target = utils.project_root / ".gitignore"
        if target.exists():
            existing = target.read_text(encoding="utf-8")
            if self._REUSE_MARKER in existing:
                return True
            content = existing.rstrip("\n") + "\n\n" + content
        return utils.write_file(
            target_file=".gitignore",
            content=content,
            is_safe=False,
        )

    @override
    async def validate_uri(self, repo_uri: str) -> None:
        remote_options = await ensure_repo_uri_allowed(repo_uri)

        git = GitUtils(
            uri=repo_uri,
            git_provider=system_config.git.provider,
            cwd=Path(tempfile.gettempdir()),
            remote_options=remote_options,
        )
        if not await git.ls_remote():
            # git's stderr names hosts, ports and paths; log it, never return it.
            logging.warning(f"git ls-remote failed for {repo_uri}: {git.error_msg}")
            raise InvalidRepoURI(message=REJECTED_MESSAGE, error_code=400)

    @override
    async def setup_call_dir(
        self,
        session_id: UUID,
        repo_uri: str,
        branch: str,
    ) -> Path:
        call_id = uuid4()
        call_dir = self._base / str(session_id) / str(call_id)
        call_dir.parent.mkdir(parents=True, exist_ok=True)

        # GitUtils.clone_repository clones into `cwd / repository_name`.
        # We want it to land at `call_dir`, so cwd=parent and repository_name=call_id.
        # The clone runs the repo_uri guard again, so every call of a session
        # (not just the first, validated one) connects to an address vetted
        # right before it, and the pin lands in the clone's .git/config.
        git = GitUtils(
            uri=repo_uri,
            git_provider=system_config.git.provider,
            cwd=call_dir.parent,
        )
        ok = await git.clone_repository(
            repo_url=repo_uri,
            repository_name=str(call_id),
        )
        if not ok:
            raise GitError("git clone failed", 500)

        if not self.__add_terraform_gitignore(call_dir):
            logging.warning("terraform gitignore couldn't be created")

        git = GitUtils(
            uri=repo_uri,
            git_provider=system_config.git.provider,
            cwd=call_dir,
        )
        await git.checkout(branch)
        await git.commit_and_push(branch)
        return call_dir

    @override
    def cleanup(self, call_dir: Path) -> None:
        shutil.rmtree(call_dir, ignore_errors=True)

    @override
    def pinned_dir(self, session_id: UUID) -> Path:
        return self._base / str(session_id) / "pinned"

    @override
    def pin_workspace(self, session_id: UUID, call_dir: Path) -> None:
        pinned = self.pinned_dir(session_id)
        shutil.rmtree(pinned, ignore_errors=True)
        _ = call_dir.rename(pinned)

    @override
    def discard_pinned(self, session_id: UUID) -> None:
        shutil.rmtree(self.pinned_dir(session_id), ignore_errors=True)

    @override
    def pinned_plan_path(self, session_id: UUID) -> Path | None:
        pinned = self.pinned_dir(session_id)
        plan = pinned / system_config.paths.session_plan_filename
        if not pinned.is_dir() or not plan.is_file():
            return None
        return plan
