# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic

"""Workspace tools confine every path to the working directory.

The system prompt hands the agent the working directory as an absolute
path, so absolute paths inside it must work like their relative form,
while anything resolving outside of it (``..``, ``/``) is rejected.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from src.domains.dto import ToolCallDTO, ToolResultDTO
from src.infrastructure.filesystem.file_system import FileSystemUtils
from src.infrastructure.tools.tool_registry_workspace import ToolRegistryWorkspace


class TestWorkspaceTools(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "repo" / "iac"
        self.root.mkdir(parents=True)
        (self.root / "main.tf").write_text('resource "x" "y" {}\n')
        (self.root / "modules").mkdir()
        (self.tmp / "repo" / "outside.tf").write_text("secret\n")
        self.registry = ToolRegistryWorkspace(
            filesystem=FileSystemUtils(self.root), git=MagicMock(), llm=MagicMock()
        )

    def tearDown(self):
        shutil.rmtree(self.tmp)

    async def _run(self, name: str, **parameters: Any) -> ToolResultDTO:
        return await self.registry.execute_tool(
            ToolCallDTO(id="call_1", name=name, parameters=parameters)
        )

    async def test_list_dir_relative_and_absolute_are_equivalent(self):
        for path in [".", "./", str(self.root)]:
            result = await self._run("list_dir", relative_workspace_path=path)
            self.assertTrue(result.success, result.error_message)
            self.assertEqual(
                result.result,
                {"path": ".", "files": ["main.tf"], "directories": ["modules"]},
            )

    async def test_parent_and_outside_paths_are_rejected(self):
        for path in [
            "..",
            "../outside.tf",
            "modules/../../outside.tf",
            "/",
            str(self.tmp),
        ]:
            result = await self._run("list_dir", relative_workspace_path=path)
            self.assertFalse(result.success, path)
            self.assertIn("outside the working directory", result.error_message)
            result = await self._run("read_file", target_file=path)
            self.assertFalse(result.success, path)

    async def test_read_file_accepts_absolute_path_inside_root(self):
        result = await self._run("read_file", target_file=str(self.root / "main.tf"))
        self.assertTrue(result.success, result.error_message)
        self.assertEqual(result.result["file"], "main.tf")

    async def test_read_missing_file_reports_not_found(self):
        result = await self._run("read_file", target_file="variables.tf")
        self.assertFalse(result.success)
        self.assertIn("variables.tf was not present", result.error_message)

    async def test_write_absolute_path_lands_in_root(self):
        result = await self._run(
            "write_to_file", target_file=str(self.root / "versions.tf"), content="x"
        )
        self.assertTrue(result.success, result.error_message)
        self.assertEqual((self.root / "versions.tf").read_text(), "x")

    async def test_delete_missing_file_reports_not_found(self):
        result = await self._run("delete_file", target_file="nope.tf")
        self.assertFalse(result.success)
        self.assertIn("does not exist", result.error_message)

    async def test_grep_returns_paths_relative_to_root(self):
        result = await self._run(
            "bulk_grep_search", searches=[{"query": "-?resource"}], explanation="x"
        )
        self.assertTrue(result.success, result.error_message)
        self.assertEqual(result.result[0]["matches"], ['main.tf:1:resource "x" "y" {}'])
        self.assertFalse(result.result[0]["truncated"])


if __name__ == "__main__":
    unittest.main()
