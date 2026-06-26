# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Literal, override

from src.domains.dto import PullRequestDTO
from src.domains.interfaces.git_interface import IGit
from src.infrastructure.filesystem.cli import Cli
from src.infrastructure.filesystem.git.providers import GitProviderFactory
from src.shared.constants import GitProviderName
from src.shared.exceptions import ExceptionHandler
from src.shared.config import system_config
from src.shared.logger import logging


class GitUtils(IGit):
    def __init__(
        self,
        git_provider: GitProviderName,
        cwd: Path = None,
        branch: str = None,
    ):
        self.__provider = GitProviderFactory(git_provider).get()
        self.__cli: Cli = Cli(
            (cwd if cwd else system_config.paths.upload_folder).resolve().as_posix(),
        )
        self.__date = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.__branch: str = branch if branch else f"Nebula/timestamp_{self.__date}"
        self.__error_msg: str = ""

    @property
    @override
    def branch(self) -> str:
        return self.__branch

    @property
    @override
    def error_msg(self) -> str:
        return self.__error_msg

    @override
    async def ls_remote(self, repo_uri: str) -> bool:
        logging.info(f"git ls-remote {repo_uri}")
        return self._handle_return_code(
            await self.__cli.execute(
                ["git", "ls-remote", "--exit-code", repo_uri],
                20,
            )
        )

    @override
    async def clone_repository(
        self,
        repo_url: str,
        repository_name: str,
        branch: str | None = None,
        create_branch: bool = False,
    ) -> bool:
        cmd = ["git", "clone", "--depth", "1"]
        if branch and not create_branch:
            cmd.extend(["--branch", branch])
        cmd.extend([repo_url, repository_name])
        logging.info(f"git clone {repo_url}")
        if not self._handle_return_code(await self.__cli.execute(cmd)):
            return False
        if create_branch and branch:
            clone_dir = (Path(self.__cli.cwd) / repository_name).resolve()
            checkout_cli = Cli(cwd=str(clone_dir))
            if not self._handle_return_code(
                await checkout_cli.execute(["git", "checkout", "-b", branch])
            ):
                return False
        return True

    @override
    async def push_branch(self, branch: str) -> bool:
        logging.info(f"git push --set-upstream origin {branch}")

        return self._handle_return_code(
            await self.__cli.execute(
                ["git", "push", "--set-upstream", "origin", branch]
            )
        )

    @override
    async def checkout(self) -> None:
        if not await self._checkout_branch(target_branch=self.__branch):
            raise ExceptionHandler(error_code=500, message=self.__error_msg)

    @override
    async def commit(self) -> None:
        if not await self._commit_changes() or not await self._push_commits():
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
            base=await self.get_default_branch(),
            title=title,
            description=description,
        )

    @override
    async def complete_pr(self, repository_url: str, pr_id: int) -> None:
        await self.__provider.complete_pr(repository_url, pr_id)

    @override
    async def get_remote_url(self) -> str:
        if not self._handle_return_code(
            cmd := await self.__cli.execute(
                [
                    "git",
                    "remote",
                    "get-url",
                    "origin",
                ]
            )
        ):
            raise ExceptionHandler(
                message=self.__error_msg,
                error_code=502,
            )
        return cmd.stdout.decode().strip().rsplit("/", 1)[-1]

    @override
    async def get_default_branch(self) -> str:
        if not self._handle_return_code(
            cmd := await self.__cli.execute(
                [
                    "git",
                    "rev-parse",
                    "--abbrev-ref",
                    "origin/HEAD",
                ]
            )
        ):
            raise ExceptionHandler(
                message=self.__error_msg,
                error_code=502,
            )
        return cmd.stdout.decode().strip().rsplit("/", 1)[-1]

    @override
    async def show_diff(self) -> str:
        """show_diff returns a plain text string containing the diff for all the STAGED and COMMITED files
        SINCE the current branch diverged from the default branch
        """
        if not self._handle_return_code(
            cmd := await self.__cli.execute(
                [
                    "git",
                    "--no-pager",
                    "diff",
                    "--no-color",
                    "--find-renames",
                    "--no-prefix",
                    "--ignore-space-change",
                    "--relative",
                    await self._get_default_branch_commit_id(),
                ]
            )
        ):
            raise ExceptionHandler(
                message=self.__error_msg,
                error_code=502,
            )
        return cmd.stdout.decode()

    @override
    async def get_changed_files(
        self, diff_filter: Literal["A", "M", "AM"]
    ) -> list[str]:
        """This function return a list of files that has been modified or created
        since the current branch has been created based on the given filter.
        A: added
        M: modified
        """
        cmd = [
            "git",
            "--no-pager",
            "diff",
            "--name-only",
            f"--diff-filter={diff_filter}",
            "--relative",
            await self._get_default_branch_commit_id(),
            "HEAD",
        ]
        if not self._handle_return_code(output := await self.__cli.execute(cmd)):
            raise ExceptionHandler(
                error_code=500,
                message=f"Git error when fetching changed files: {self.__error_msg}",
            )
        return output.stdout.decode("utf-8").strip().splitlines()

    async def _get_default_branch_commit_id(self) -> str:
        if not self._handle_return_code(
            cmd := await self.__cli.execute(
                ["git", "merge-base", await self.get_default_branch(), "HEAD"]
            )
        ):
            raise ExceptionHandler(
                error_code=500,
                message=f"Git error when merging base: {self.__error_msg}",
            )
        return cmd.stdout.decode("utf-8").strip()

    # note: target_branch support for possible use. Otherwise it is always self.__branch
    async def _checkout_branch(self, target_branch: str) -> bool:
        if await self._show_current_branch() != target_branch:
            all_branches = await self._show_all_branches()
            if all_branches.find(self.__branch) == -1:
                logging.info(f"git new branch checkout {target_branch}")
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
            else:
                logging.info(f"git checkout {target_branch}")
                return self._handle_return_code(
                    await self.__cli.execute(["git", "checkout", target_branch])
                )
        return True

    async def _show_current_branch(self) -> str:
        cmd = await self.__cli.execute(["git", "branch", "--show-current"])
        return cmd.stdout.decode("utf-8").strip("\n")

    async def _show_all_branches(self) -> str:
        cmd = await self.__cli.execute(["git", "--no-pager", "branch", "-a"])
        return cmd.stdout.decode("utf-8")

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
        if cmd.stdout.decode("utf-8").strip():
            return True
        return False

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

    async def _push_commits(self) -> bool:
        logging.info(f"git push origin/{self.__branch}")
        return self._handle_return_code(
            await self.__cli.execute(
                ["git", "push", "--set-upstream", "origin", self.__branch]
            )
        )

    def _handle_return_code(self, cmd: subprocess.CompletedProcess[bytes]) -> bool:
        if cmd.returncode != 0:
            self.__error_msg = (cmd.stderr + cmd.stdout).decode()
            logging.error(self.__error_msg)
            return False
        return True
