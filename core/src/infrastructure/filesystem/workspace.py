# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import shutil
import tempfile
from pathlib import Path
from typing import final, override
from uuid import UUID

from src.domains.interfaces.workspace_interface import IWorkspace
from src.infrastructure.exceptions import InvalidRepoURI
from src.infrastructure.filesystem.git.git_utils import GitUtils
from src.shared.config import system_config
from src.shared.logger import logging


@final
class WorkspaceService(IWorkspace):
    """Implements IWorkspace using GitUtils for git ops and shutil for filesystem ops."""

    def __init__(self, base_path: Path | None = None):
        self._override_base = base_path

    @property
    def _base(self) -> Path:
        return self._override_base or system_config.paths.upload_folder

    @override
    async def validate_uri(self, repo_uri: str) -> None:

        git = GitUtils(
            git_provider=system_config.git.provider,
            cwd=Path(tempfile.gettempdir()),
        )
        if not await git.ls_remote(repo_uri):
            msg = git.error_msg or f"Cannot reach repository: {repo_uri}"
            logging.warning(f"git ls-remote failed for {repo_uri}: {msg}")
            raise InvalidRepoURI(message=msg, error_code=400)

    @override
    async def setup_call_dir(
        self,
        *,
        session_id: UUID,
        call_id: UUID,
        repo_uri: str,
        branch: str | None,
        create_branch: bool = False,
    ) -> Path:
        call_dir = self._base / "sessions" / str(session_id) / str(call_id)
        call_dir.parent.mkdir(parents=True, exist_ok=True)

        # GitUtils.clone_repository clones into `cwd / repository_name`.
        # We want it to land at `call_dir`, so cwd=parent and repository_name=call_id.
        git = GitUtils(git_provider=system_config.git.provider, cwd=call_dir.parent)
        ok = await git.clone_repository(
            repo_url=repo_uri,
            repository_name=str(call_id),
            branch=branch,
            create_branch=create_branch,
        )
        if not ok:
            shutil.rmtree(call_dir, ignore_errors=True)
            raise RuntimeError(f"git clone failed: {git.error_msg}")
        return call_dir

    @override
    async def push_and_cleanup(self, *, call_dir: Path, branch: str) -> None:
        git = GitUtils(git_provider=system_config.git.provider, cwd=call_dir)
        ok = await git.push_branch(branch)
        if not ok:
            self.cleanup(call_dir)
            raise RuntimeError(f"git push failed: {git.error_msg}")
        self.cleanup(call_dir)

    @override
    def cleanup(self, call_dir: Path) -> None:
        shutil.rmtree(call_dir, ignore_errors=True)
