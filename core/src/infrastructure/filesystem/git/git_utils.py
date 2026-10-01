# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0
import hashlib
import re

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Literal, override
from urllib.parse import urlparse, urlunparse

from src.domains.dto import PullRequestDTO
from src.domains.interfaces.git_interface import IGit
from src.infrastructure.exceptions import CliTimeoutError, RepositoryUnreachable
from src.infrastructure.filesystem.cli import Cli
from src.infrastructure.filesystem.git.providers import GitProviderFactory
from src.shared.config.system_config import system_config
from src.shared.constants import GitProviderName
from src.shared.exceptions import ExceptionHandler
from src.shared.logger import logging


class GitUtils(IGit):
    def __init__(
        self,
        uri: str,
        git_provider: GitProviderName,
        cwd: Path = None,
    ):
        self.__uri = uri
        self.__provider = GitProviderFactory(git_provider).get()
        self.__cli: Cli = Cli(
            (cwd if cwd else system_config.paths.upload_folder).resolve().as_posix(),
        )
        self.__date = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.__error_msg: str = ""

    @property
    @override
    def error_msg(self) -> str:
        return self.__error_msg

    @override
    async def ls_remote(self) -> bool:
        logging.info(f"git ls-remote {self.__uri}")
        try:
            result = await self.__cli.execute(
                ["git", "ls-remote", "--exit-code", self.__uri],
                20,
            )
        except CliTimeoutError as e:
            self.__error_msg = e.message
            return False
        return self._handle_return_code(result)

    @override
    async def clone_repository(
        self,
        repo_url: str,
        repository_name: str,
        *extra_args: str,
        timeout: int = 300,
    ) -> bool:
        cmd = ["git", "clone", "--depth", "1"]
        cmd.extend(extra_args)
        cmd.extend([repo_url, repository_name])
        parsed = urlparse(repo_url)
        safe_uri = urlunparse(parsed._replace(netloc=parsed.hostname or ""))
        try:
            result = await self.__cli.execute(cmd, timeout)
        except CliTimeoutError as e:
            self.__error_msg = e.message
            logging.error(f"git clone timed out for {safe_uri}")
            return False
        if not self._handle_return_code(result):
            logging.error(
                f"git clone failed for {safe_uri}"
                + (
                    " (original url included credentials)"
                    if repo_url != safe_uri
                    else ""
                )
            )
            return False
        logging.info(f"git clone {safe_uri}")
        return True

    async def ls_tree(self, cwd: Path) -> list[str]:
        """Return all tracked file paths via ``git ls-tree -r HEAD --name-only``."""
        cli = Cli(cwd=str(cwd))
        result = await cli.execute(
            ["git", "ls-tree", "-r", "--name-only", "HEAD"],
            30,
        )
        if not self._handle_return_code(result):
            raise ExceptionHandler(f"git ls-tree failed: {self.error_msg}", 502)
        return result.stdout.decode().splitlines()

    @override
    async def push_branch(self, branch: str) -> bool:
        logging.info(f"git push --set-upstream origin {branch}")

        return self._handle_return_code(
            await self.__cli.execute(
                ["git", "push", "--set-upstream", "origin", branch]
            )
        )

    @override
    async def checkout(self, branch: str) -> None:
        if not await self._checkout_branch(target_branch=branch):
            raise ExceptionHandler(error_code=500, message=self.__error_msg)

    @override
    async def commit_and_push(self, branch: str) -> None:
        if not await self._commit_changes() or not await self._push_commits(branch):
            raise ExceptionHandler(error_code=500, message=self.__error_msg)

    @override
    async def create_pr(
        self,
        repository_url: str,
        head_branch: str,
        title: str,
        description: str,
    ) -> PullRequestDTO:
        return await self.__provider.create_pr(
            repository_url=repository_url,
            head=head_branch,
            base=await self.get_default_branch(True),
            title=title,
            description=description,
        )

    @override
    async def complete_pr(self, pr_id: int) -> None:
        await self.__provider.complete_pr(self.__uri, pr_id)

    @override
    async def get_default_branch(self, ls_remote: bool = False) -> str:
        if ls_remote:
            cmd = [
                "git",
                "ls-remote",
                "--symref",
                self.__uri,
                "HEAD",
            ]
        else:
            cmd = [
                "git",
                "rev-parse",
                "--abbrev-ref",
                "origin/HEAD",
            ]
        logging.debug(
            ["git", "ls-remote", "--symref", "<repository>", "HEAD"]
            if ls_remote
            else cmd
        )
        try:
            result = await self.__cli.execute(cmd)
        except CliTimeoutError as e:
            raise RepositoryUnreachable(502) from e
        if not self._handle_return_code(result):
            if ls_remote:
                raise RepositoryUnreachable(502)
            raise ExceptionHandler(
                message=self.__error_msg,
                error_code=502,
            )
        if ls_remote:
            match = re.search(r"ref:\s+refs/heads/(\S+)\s+HEAD", result.stdout.decode())
            if match is None:
                raise ExceptionHandler(
                    message="No match git default branch ls-remote", error_code=500
                )
            return match.group(1)
        return result.stdout.decode().strip().rsplit("/", 1)[-1]

    @override
    async def show_diff(
        self,
        working_tree: bool,
        full_content: bool,
        file_path: str = None,
    ) -> str:
        cmd = [
            "git",
            "--no-pager",
            "diff",
            "--no-color",
            "--find-renames",
            "--no-prefix",
            "--ignore-space-change",
            "--relative",
            "HEAD",
        ]
        if full_content:
            cmd.insert(3, "--unified=1000")
        if not working_tree:
            cmd.insert(cmd.index("HEAD"), await self._get_default_branch_commit_id())
        if file_path:
            cmd.extend(["--", file_path])
        logging.debug(cmd)
        if not self._handle_return_code(cmd := await self.__cli.execute(cmd)):
            raise ExceptionHandler(
                message=self.__error_msg,
                error_code=502,
            )
        return cmd.stdout.decode()

    @override
    async def get_workspace_revision(self) -> str:
        cmd = [
            "git",
            "status",
            "--porcelain=v2",
            "--branch",
            "--untracked-files=all",
        ]
        logging.debug(cmd)
        if not self._handle_return_code(output := await self.__cli.execute(cmd)):
            raise ExceptionHandler(
                error_code=502,
                message=f"Git error when reading the workspace revision: {self.__error_msg}",
            )
        return hashlib.sha256(output.stdout).hexdigest()

    @override
    async def get_untracked_files(self) -> list[str]:
        cmd = [
            "git",
            "--no-pager",
            "ls-files",
            "--others",
            "--exclude-standard",
        ]
        logging.debug(cmd)
        if not self._handle_return_code(output := await self.__cli.execute(cmd)):
            raise ExceptionHandler(
                error_code=500,
                message=f"Git error when fetching changed files: {self.__error_msg}",
            )
        return output.stdout.decode("utf-8").strip().splitlines()

    @override
    async def get_changed_files(
        self,
        working_tree: bool,
        diff_filter: Literal["A", "M", "D", "AMD"],
    ) -> list[str]:
        cmd = [
            "git",
            "--no-pager",
            "diff",
            "--name-only",
            f"--diff-filter={diff_filter}",
            "--relative",
            "HEAD",
        ]
        if not working_tree:
            cmd.insert(6, await self._get_default_branch_commit_id())
        logging.debug(cmd)
        if not self._handle_return_code(output := await self.__cli.execute(cmd)):
            raise ExceptionHandler(
                error_code=500,
                message=f"Git error when fetching changed files: {self.__error_msg}",
            )
        return output.stdout.decode("utf-8").strip().splitlines()

    async def _get_default_branch_commit_id(self) -> str:
        default_branch = await self.get_default_branch()
        merge_base = ["git", "merge-base", default_branch, "HEAD"]
        cmd = await self.__cli.execute(merge_base)
        if cmd.returncode != 0 and await self._is_shallow_repository():
            # Shallow clones truncate history, so the branches can look
            # disconnected; fetch the full history and retry once.
            if not await self._fetch_unshallow(
                default_branch, await self._show_current_branch()
            ):
                raise ExceptionHandler(
                    error_code=500,
                    message=f"Git error when unshallowing: {self.__error_msg}",
                )
            cmd = await self.__cli.execute(merge_base)
        if not self._handle_return_code(cmd):
            raise ExceptionHandler(
                error_code=500,
                message=f"Git error when merging base: {self.__error_msg}",
            )
        return cmd.stdout.decode("utf-8").strip()

    async def _is_shallow_repository(self) -> bool:
        cmd = await self.__cli.execute(["git", "rev-parse", "--is-shallow-repository"])
        return cmd.returncode == 0 and cmd.stdout.decode("utf-8").strip() == "true"

    async def _fetch_unshallow(self, *branches: str) -> bool:
        cmd = ["git", "fetch", "--unshallow", "origin"]
        cmd.extend(
            f"refs/heads/{branch}:refs/remotes/origin/{branch}"
            for branch in dict.fromkeys(branch for branch in branches if branch)
        )
        logging.debug(cmd)
        return self._handle_return_code(await self.__cli.execute(cmd))

    async def _checkout_branch(self, target_branch: str) -> bool:
        if await self._show_current_branch() != target_branch:
            if await self._check_branch_exists(target_branch):
                cmd = [
                    "git",
                    "fetch",
                    "--depth",
                    "1",
                    "origin",
                    f"refs/heads/{target_branch}:refs/remotes/origin/{target_branch}",
                ]
                logging.debug(cmd)
                if not self._handle_return_code(await self.__cli.execute(cmd)):
                    return False

                cmd = [
                    "git",
                    "checkout",
                    "-B",
                    target_branch,
                    f"refs/remotes/origin/{target_branch}",
                ]
                logging.debug(cmd)
                return self._handle_return_code(await self.__cli.execute(cmd))
            else:
                logging.debug(f"git new branch checkout {target_branch}")
                return self._handle_return_code(
                    await self.__cli.execute(
                        [
                            "git",
                            "checkout",
                            "-b",
                            target_branch,
                            await self.get_default_branch(),
                        ]
                    )
                )
        return True

    async def _show_current_branch(self) -> str:
        cmd = await self.__cli.execute(["git", "branch", "--show-current"])
        return cmd.stdout.decode("utf-8").strip("\n")

    async def _check_branch_exists(self, branch: str) -> bool:
        try:
            cmd = await self.__cli.execute(
                [
                    "git",
                    "ls-remote",
                    "--exit-code",
                    "--heads",
                    "origin",
                    branch,
                ],
                20,
            )
        except CliTimeoutError as e:
            raise RepositoryUnreachable(502) from e
        if cmd.returncode == 0:
            return True
        if cmd.returncode == 2:
            return False
        _ = self._handle_return_code(cmd)
        raise RepositoryUnreachable(502)

    async def _delete_branch(self, target_branch: str) -> bool:
        output_checkout = await self._checkout_branch(
            target_branch=await self.get_default_branch()
        )
        if not output_checkout:
            return output_checkout
        output_delete_local_branch = self._handle_return_code(
            await self.__cli.execute(["git", "branch", "-D", target_branch])
        )
        if not output_delete_local_branch:
            return output_delete_local_branch
        return self._handle_return_code(
            await self.__cli.execute(
                ["git", "push", "origin", "--delete", target_branch]
            )
        )

    async def _are_there_changes(self) -> bool:
        cmd = await self.__cli.execute(["git", "status", "--porcelain"])
        logging.info(f"git status {cmd.stdout.decode('utf-8').strip()}")
        return cmd.stdout.decode("utf-8").strip()

    async def _add_all(self) -> bool:
        return self._handle_return_code(await self.__cli.execute(["git", "add", "-A"]))

    async def _commit_changes(self) -> bool:
        git_add = await self._add_all()
        if not git_add:
            return False
        if await self._are_there_changes():
            logging.info("git changes commited")
            return self._handle_return_code(
                await self.__cli.execute(["git", "commit", "-m", "Nebula changes"])
            )
        return True

    async def _push_commits(self, branch: str) -> bool:
        logging.info(f"git push origin/{branch}")
        return self._handle_return_code(
            await self.__cli.execute(
                ["git", "push", "--set-upstream", "origin", branch]
            )
        )

    def _handle_return_code(self, cmd: subprocess.CompletedProcess[bytes]) -> bool:
        if cmd.returncode != 0:
            self.__error_msg = (cmd.stderr + cmd.stdout).decode()
            logging.error(self.__error_msg)
            return False
        return True
