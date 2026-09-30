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
from src.infrastructure.filesystem.git.remote_guard import check_remote
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
        remote = await check_remote(repo_uri)
        git = GitUtils(
            uri=repo_uri,
            git_provider=system_config.git.provider,
            cwd=Path(tempfile.gettempdir()),
        )
        if not await git.ls_remote(*remote.command_options):
            # git's stderr stays in the server log: it can echo internal
            # hostnames, addresses and response bodies back to the caller.
            logging.warning(f"git ls-remote failed for {remote.host}: {git.error_msg}")
            raise InvalidRepoURI(
                message="Repository could not be reached. Check the URI and "
                + "that Nebula has access to it.",
                error_code=400,
            )

    @override
    async def setup_call_dir(
        self,
        session_id: UUID,
        repo_uri: str,
        branch: str,
    ) -> Path:
        # Re-checked here rather than trusted from validate_uri: this runs
        # later, in the background, and DNS may answer differently by now.
        remote = await check_remote(repo_uri)
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
            repo_uri,
            str(call_id),
            *remote.clone_options,
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
