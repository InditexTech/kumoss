# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic, reportAssignmentType=false, reportAttributeAccessIssue=false
import unittest
from pathlib import Path

from src.infrastructure.filesystem import FileSystemUtils, GitUtils
from tests.setups import setup_repository, clean_resources
from tests.settings import Settings
from src.shared.logger import logging


class TestGitUtils(unittest.IsolatedAsyncioTestCase):
    PROJECTS: list[tuple[str, str]] = [
        ("pixia", "gcp"),
        ("isaiarqdat", "azure"),
        ("datamap", "gcp"),
    ]
    git_utils: GitUtils = None

    @classmethod
    async def asyncSetUp(cls):
        await setup_repository()
        file_utils = FileSystemUtils(
            root=Path(
                Settings.UPLOAD_DIR
                / Settings.DEFAULT_PROJECT_UID
                / Settings.DEFAULT_PROJECT_ENV
            ),
            file_ext=["tf", "tfvars"],
        )
        cls.git_utils = GitUtils(file_utils.project_root)
        await cls.git_utils.checkout()

    @classmethod
    async def asyncTearDown(cls):
        clean_resources()

    async def test_get_remote_url(self):
        await setup_repository(self.PROJECTS)
        for pair in self.PROJECTS:
            git = GitUtils(Settings.UPLOAD_DIR / f"{pair[0]}_{Settings.SESSION_ID}")
            output = await git.get_remote_url()
            if pair[1] == "gcp":
                self.assertIn(
                    output,
                    [
                        f"devops.project.gcp.{pair[0]}",
                        f"devops.project.gcp.bq.{pair[0]}",
                    ],
                )
            else:
                self.assertEqual(output, f"devops.project.{pair[0]}")
            logging.debug(output)
        clean_resources([f"{pair[0]}_{Settings.SESSION_ID}" for pair in self.PROJECTS])

    async def test_changed_files(self):
        file_name = "test_file.tf"
        self.__write_to_file(file_name)
        await self.git_utils.commit()

        output = await self.git_utils.get_changed_files("A")
        self.assertEqual(output, [file_name])
        output = await self.git_utils.get_changed_files("M")
        self.assertEqual(output, [])
        output = await self.git_utils.get_changed_files("AM")
        self.assertEqual(output, [file_name])

    async def test_get_default_branch(self):
        self.assertEqual(await self.git_utils.get_default_branch(), "master")

    async def test_get_default_branch_commit_id(self):
        self.assertIsInstance(await self.git_utils._get_default_branch_commit_id(), str)

    async def test_show_diff(self):
        self.assertEqual(await self.git_utils.show_diff(), "")
        self.__write_to_file("test_file.tf")
        await self.git_utils.commit()
        self.assertIsInstance(await self.git_utils.show_diff(), str)

    def __write_to_file(self, file_name: str):
        with open(
            Settings.UPLOAD_DIR
            / Settings.DEFAULT_PROJECT_UID
            / Settings.DEFAULT_PROJECT_ENV
            / file_name,
            "w",
        ) as f:
            f.write("test content")


if __name__ == "__main__":
    unittest.main()
