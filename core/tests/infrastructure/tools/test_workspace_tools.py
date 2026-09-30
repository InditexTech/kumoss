# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic, reportArgumentType=false

"""Workspace tools confine every path to the working directory.

The system prompt hands the agent the working directory as an absolute
path, so absolute paths inside it must work like their relative form,
while anything resolving outside of it (``..``, ``/``) is rejected. The
entries Nebula manages inside it (git metadata, the gitignore, the backend
override with the state-store credentials) are never exposed.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

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
        (self.root / "modules" / "vars.tf").write_text("\n")
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

    async def test_list_dir_hides_ignored_entries_like_grep(self):
        (self.root / ".gitignore").write_text("**/.terraform/*\n*_override.tf\n")
        (self.root / ".terraform").mkdir()
        (self.root / ".terraform" / "terraform.tfstate").write_text("{}")
        (self.root / "backend_override.tf").write_text("terraform {}\n")
        (self.root / "modules" / "network.tf").write_text("\n")

        result = await self._run("list_dir", relative_workspace_path=".")
        self.assertTrue(result.success, result.error_message)
        self.assertEqual(result.result["files"], ["main.tf"])
        self.assertEqual(result.result["directories"], ["modules"])

    async def test_list_dir_missing_directory_reports_relative_path(self):
        result = await self._run("list_dir", relative_workspace_path="nope")
        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "Directory nope does not exist")

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

    async def test_protected_entries_are_rejected_by_every_tool(self):
        (self.root / ".git").mkdir()
        (self.root / ".git" / "config").write_text("[core]\n")
        (self.root / ".gitignore").write_text("*_override.tf\n")
        (self.root / "backend_override.tf").write_text('access_key = "k"\n')
        calls: list[tuple[str, dict[str, Any]]] = [
            ("read_file", {"target_file": ".git/config"}),
            ("read_file", {"target_file": "backend_override.tf"}),
            ("read_file", {"target_file": str(self.root / "backend_override.tf")}),
            ("list_dir", {"relative_workspace_path": ".git"}),
            ("delete_file", {"target_file": ".gitignore"}),
            ("delete_file", {"target_file": "backend_override.tf"}),
            ("write_to_file", {"target_file": ".git/hooks/x.tf", "content": "x"}),
            ("write_to_file", {"target_file": "modules/.git/x.tf", "content": "x"}),
            ("replace_in_file", {"target_file": "backend_override.tf", "diff": "x"}),
        ]
        for name, parameters in calls:
            result = await self._run(name, **parameters)
            self.assertFalse(result.success, (name, parameters))
            self.assertIn("managed by Nebula", result.error_message)
        self.assertTrue((self.root / ".gitignore").exists())
        self.assertFalse((self.root / ".git" / "hooks").exists())

    async def test_grep_include_pattern_cannot_reach_protected_entries(self):
        (self.root / ".git").mkdir()
        (self.root / ".git" / "config").write_text("token = leak\n")
        (self.root / ".gitignore").write_text("# leak\n")
        (self.root / "backend_override.tf").write_text('access_key = "leak"\n')

        for include in ["*", "**", ".git/**", "*.tf", "backend_override.tf"]:
            result = await self._run(
                "bulk_grep_search",
                searches=[{"query": "leak", "include_pattern": include}],
            )
            self.assertTrue(result.success, result.error_message)
            self.assertEqual(result.result[0]["matches"], [], include)

    async def test_delete_only_removes_files_the_agent_could_write(self):
        (self.root / "README.md").write_text("docs\n")

        result = await self._run("delete_file", target_file="README.md")
        self.assertFalse(result.success)
        self.assertIn("File extension violation", result.error_message)
        self.assertTrue((self.root / "README.md").exists())

        result = await self._run("delete_file", target_file="main.tf")
        self.assertTrue(result.success, result.error_message)
        self.assertFalse((self.root / "main.tf").exists())

    async def test_diff_history_skips_untracked_links_leaving_the_root(self):
        (self.root / "new.tf").write_text("new\n")
        (self.root / "leak.tf").symlink_to(self.tmp / "repo" / "outside.tf")
        git = MagicMock()
        git.show_diff = AsyncMock(return_value="")
        git.get_untracked_files = AsyncMock(return_value=["leak.tf", "new.tf"])
        registry = ToolRegistryWorkspace(
            filesystem=FileSystemUtils(self.root), git=git, llm=MagicMock()
        )

        result = await registry.execute_tool(
            ToolCallDTO(id="call_1", name="diff_history", parameters={})
        )
        self.assertTrue(result.success, result.error_message)
        self.assertEqual(result.result["changes"], [["new.tf:\nnew\n"]])


if __name__ == "__main__":
    unittest.main()
