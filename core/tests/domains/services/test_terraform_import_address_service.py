# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for TerraformImportAddressService.

The mapping agent cannot rebuild a cloud resource id from a generated
block alone: the block carries the resource name, never the subscription
or account it lives under. The ids the round selected must therefore
reach its prompt, or the agent reports nothing to import.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock

from src.domains.dto import ToolResultDTO
from src.domains.services.terraform_import_address_service import (
    TerraformImportAddressService,
)
from src.shared.constants import PromptsLibrary

SELECTED_IDS = [
    "/subscriptions/sub-1/resourceGroups/rg/providers/"
    "Microsoft.Storage/storageAccounts/sttestdev002",
]


class TestTerraformImportAddressService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tool_svc = MagicMock()
        self.llm_svc = AsyncMock()
        self.template_svc = AsyncMock()
        self.history = MagicMock()
        self.service = TerraformImportAddressService(
            tool_service=self.tool_svc,
            llm_service=self.llm_svc,
            template_service=self.template_svc,
        )

    def __answer(self, imports: list[dict[str, str]]) -> None:
        self.llm_svc.generate.return_value = ToolResultDTO(
            name="iac_import",
            tool_call_id="call-1",
            success=True,
            result={"status": bool(imports), "imports": imports},
        )

    async def test_selected_ids_reach_the_prompt(self):
        self.__answer([])

        _ = await self.service.get_import_addresses(self.history, SELECTED_IDS)

        self.template_svc.render.assert_awaited_once_with(
            PromptsLibrary.IMPORT_ADDRESSES, selected_ids=SELECTED_IDS
        )

    async def test_reported_imports_become_address_id_pairs(self):
        self.__answer(
            [
                {
                    "address": "azurerm_storage_account.sttestdev002",
                    "resource_id": SELECTED_IDS[0],
                }
            ]
        )

        imports = await self.service.get_import_addresses(self.history, SELECTED_IDS)

        self.assertEqual(
            [("azurerm_storage_account.sttestdev002", SELECTED_IDS[0])], imports
        )
