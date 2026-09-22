# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for TerraformImportAddressService.

The service cannot rebuild a cloud resource id from a generated block
alone: the block carries the resource name, never the subscription or
account it lives under. It therefore walks the selected ids and looks
each one up in the Terraform the session branch added, pairing on the
name the generator derived from the id. An id the diff cannot resolve to
exactly one block is left out: a missed import shows up later as drift,
a wrong one corrupts the Terraform state.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock

from src.domains.services.terraform_import_address_service import (
    TerraformImportAddressService,
)
from src.shared.exceptions import ExceptionHandler

STORAGE_ID = (
    "/subscriptions/sub-1/resourceGroups/rg/providers/"
    "Microsoft.Storage/storageAccounts/sttestdev002"
)
GROUP_ID = "/subscriptions/sub-1/resourceGroups/rg"

DIFF = """diff --git main.tf main.tf
index 1111111..2222222 100644
--- main.tf
+++ main.tf
@@ -1,3 +1,8 @@
 resource "azurerm_resource_group" "existing" {
   name = "rg"
 }
+
+resource "azurerm_storage_account" "sta_001" {
+  name                = "sttestdev002"
+  resource_group_name = azurerm_resource_group.existing.name
+}
"""


def _diff(file_name: str, *added: str) -> str:
    """Build a diff that adds the given lines to a single file."""
    header = f"diff --git {file_name} {file_name}\n--- {file_name}\n+++ {file_name}\n"
    return header + "".join(f"+{line}\n" for line in added)


class TestTerraformImportAddressService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.git = AsyncMock()
        self.git.show_diff.return_value = ""
        self.git.get_untracked_files.return_value = []
        self.files = MagicMock()
        self.service = TerraformImportAddressService(git=self.git, files=self.files)

    async def test_added_block_pairs_with_the_id_sharing_its_name(self):
        self.git.show_diff.return_value = DIFF

        imports = await self.service.get_import_addresses([STORAGE_ID])

        self.assertEqual([("azurerm_storage_account.sta_001", STORAGE_ID)], imports)
        self.git.show_diff.assert_awaited_once_with(
            working_tree=False, full_content=False
        )

    async def test_block_without_a_literal_name_falls_back_to_its_label(self):
        self.git.show_diff.return_value = _diff(
            "main.tf",
            'resource "azurerm_storage_account" "sttestdev002" {',
            "  name = local.storage_name",
            "}",
        )

        imports = await self.service.get_import_addresses([STORAGE_ID])

        self.assertEqual(
            [("azurerm_storage_account.sttestdev002", STORAGE_ID)], imports
        )

    async def test_untracked_files_contribute_their_blocks(self):
        self.git.get_untracked_files.return_value = ["storage.tf"]
        self.files.read_file.return_value = (
            'resource "azurerm_storage_account" "sta_001" {\n'
            '  name = "sttestdev002"\n'
            "}\n"
        )

        imports = await self.service.get_import_addresses([STORAGE_ID])

        self.assertEqual([("azurerm_storage_account.sta_001", STORAGE_ID)], imports)

    async def test_pre_existing_blocks_are_ignored(self):
        self.git.show_diff.return_value = DIFF

        imports = await self.service.get_import_addresses([GROUP_ID])

        self.assertEqual([], imports)

    async def test_changes_outside_terraform_files_are_ignored(self):
        self.git.show_diff.return_value = _diff(
            "README.md",
            'resource "azurerm_storage_account" "sta_001" {',
            '  name = "sttestdev002"',
            "}",
        )

        imports = await self.service.get_import_addresses([STORAGE_ID])

        self.assertEqual([], imports)

    async def test_an_id_matching_several_blocks_is_skipped(self):
        self.git.show_diff.return_value = _diff(
            "main.tf",
            'resource "azurerm_storage_account" "first" {',
            '  name = "sttestdev002"',
            "}",
            'resource "azurerm_storage_account" "second" {',
            '  name = "sttestdev002"',
            "}",
        )

        imports = await self.service.get_import_addresses([STORAGE_ID])

        self.assertEqual([], imports)

    async def test_a_block_is_imported_once(self):
        self.git.show_diff.return_value = _diff(
            "main.tf",
            'resource "azurerm_storage_account" "sta_001" {',
            '  name = "sttestdev002"',
            "}",
        )
        twin_id = STORAGE_ID.replace("sub-1", "sub-2")

        imports = await self.service.get_import_addresses([STORAGE_ID, twin_id])

        self.assertEqual([("azurerm_storage_account.sta_001", STORAGE_ID)], imports)

    async def test_an_unreadable_untracked_file_does_not_stop_the_mapping(self):
        self.git.show_diff.return_value = DIFF
        self.git.get_untracked_files.return_value = ["unreadable.tf"]
        self.files.read_file.side_effect = ExceptionHandler(
            message="No such file", error_code=404
        )

        imports = await self.service.get_import_addresses([STORAGE_ID])

        self.assertEqual([("azurerm_storage_account.sta_001", STORAGE_ID)], imports)
