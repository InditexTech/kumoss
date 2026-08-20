# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import shutil
import tempfile
from pathlib import Path
from typing import final, override
from uuid import UUID
from uuid import uuid4

from src.domains.interfaces.workspace_interface import IWorkspace
from src.infrastructure.exceptions import GitError, InvalidRepoURI
from src.infrastructure.filesystem.file_system import FileSystemUtils
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

    def __add_terraform_gitignore(self, path: Path) -> bool:
        utils = FileSystemUtils(path)
        if Path(utils.project_root / ".gitignore").exists():
            return True
        with open(Path(__file__).resolve().parent / "terraform.gitignore", "r") as f:
            return utils.write_file(
                target_file=".gitignore",
                content=f.read(),
                is_safe=False,
            )

    @override
    async def validate_uri(self, repo_uri: str) -> None:

        git = GitUtils(
            uri=repo_uri,
            git_provider=system_config.git.provider,
            cwd=Path(tempfile.gettempdir()),
        )
        if not await git.ls_remote():
            msg = git.error_msg or f"Cannot reach repository: {repo_uri}"
            logging.warning(f"git ls-remote failed for {repo_uri}: {msg}")
            raise InvalidRepoURI(message=msg, error_code=400)

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
            raise GitError(f"git clone failed: {git.error_msg}", 500)

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
