# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from src.domains.interfaces.filesystem_interface import IFileSystem
from src.domains.interfaces.git_interface import IGit
from src.shared.logger import logging


class ProjectSetupService:
    def __init__(self, git: IGit, filesystem: IFileSystem):
        self.__git = git
        self.__filesystem = filesystem

    async def setup_project(self) -> str:
        if not self.__add_terraform_gitignore():
            logging.warning("terraform gitignore couldn't be created")
        await self.__git.checkout()
        await self.__git.commit()
        return self.__git.branch

    def __add_terraform_gitignore(self) -> bool:
        with open(Path(__file__).resolve().parent / "terraform.gitignore", "r") as f:
            if not Path(self.__filesystem.project_root / ".gitignore").exists():
                return self.__filesystem.write_file(
                    target_file=".gitignore",
                    content=f.read(),
                    is_safe=False,
                )
        return True
