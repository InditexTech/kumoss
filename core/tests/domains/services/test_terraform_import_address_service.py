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
from src.shared.constants import PromptsLibrary, ToolContext

SELECTED_IDS = [
    "/subscriptions/sub-1/resourceGroups/rg/providers/"
    "Microsoft.Storage/storageAccounts/sttestdev002",
]


class TestTerraformImportAddressService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tool_svc = MagicMock()
        self.llm_svc = AsyncMock()
        self.template_svc = AsyncMock()
        self.service = TerraformImportAddressService(
            tool_service=self.tool_svc,
            llm_service=self.llm_svc,
            template_service=self.template_svc,
        )

    def __answer(self, imports: list[dict[str, str]]) -> None:
        self.llm_svc.generate.return_value = ToolResultDTO(
            name="import_addresses",
            tool_call_id="call-1",
            success=True,
            result={"summary": "", "imports": imports},
        )

    async def test_selected_ids_reach_the_prompt(self):
        self.__answer([])

        _ = await self.service.get_import_addresses(SELECTED_IDS)

        self.template_svc.render.assert_awaited_once_with(
            PromptsLibrary.IMPORT_ADDRESSES, selected_ids=SELECTED_IDS
        )

    async def test_the_agent_can_look_up_canonical_id_casing(self):
        self.__answer([])

        _ = await self.service.get_import_addresses(SELECTED_IDS)

        # The ids it reports go straight to `terraform import`, and each
        # resource type documents its own import ID format, which is often
        # not the listed id. Settling that needs the registry, so the
        # workspace tools are not enough on their own.
        contexts = self.tool_svc.get_available_tools.call_args.kwargs["contexts"]
        self.assertIn(ToolContext.WORKSPACE_INSPECTION, contexts)
        self.assertIn(ToolContext.EXTERNAL_INFORMATION, contexts)

    async def test_reported_imports_keep_the_listed_id_they_came_from(self):
        listed_id = "arn:aws:ecs:eu-west-1:111122223333:service/prod/api"
        self.__answer(
            [
                {
                    "address": "aws_ecs_service.api",
                    "resource_id": "prod/api",
                    "listed_id": listed_id,
                }
            ]
        )

        imports = await self.service.get_import_addresses([listed_id])

        # A retry rebuilds a rejected import ID from its listed id, so the
        # listed id must survive next to the import ID it produced.
        self.assertEqual(
            [("aws_ecs_service.api", "prod/api", listed_id)],
            [(i.address, i.resource_id, i.listed_id) for i in imports],
        )
