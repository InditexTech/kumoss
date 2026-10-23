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
        self.history = MagicMock()
        self.service = TerraformImportAddressService(
            tool_service=self.tool_svc,
            llm_service=self.llm_svc,
            template_service=self.template_svc,
        )

    def __answer(
        self,
        imports: list[dict[str, str]],
        unresolved: list[dict[str, str]] | None = None,
    ) -> None:
        self.llm_svc.generate.return_value = ToolResultDTO(
            name="import_addresses",
            tool_call_id="call-1",
            success=True,
            result={
                "status": bool(imports),
                "imports": imports,
                "unresolved": unresolved or [],
            },
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

        # The ids it reports go straight to `terraform import`, and a
        # listing API does not always case a resource type the way the
        # provider parses it. Settling that needs the registry, so the
        # workspace tools are not enough on their own.
        contexts = self.tool_svc.get_available_tools.call_args.kwargs["contexts"]
        self.assertIn(ToolContext.WORKSPACE_INSPECTION, contexts)
        self.assertIn(ToolContext.EXTERNAL_INFORMATION, contexts)

    async def test_reported_imports_become_address_id_pairs(self):
        self.__answer(
            [
                {
                    "address": "azurerm_storage_account.sttestdev002",
                    "resource_id": SELECTED_IDS[0],
                }
            ]
        )

        mapping = await self.service.get_import_addresses(SELECTED_IDS)

        self.assertEqual(
            [("azurerm_storage_account.sttestdev002", SELECTED_IDS[0])],
            [(a.address, a.resource_id) for a in mapping.imports],
        )
        self.assertEqual(set(), mapping.unresolved)

    async def test_unresolved_blocks_carry_their_reason(self):
        # A block the agent could not map must reach the handler with the
        # reason, or the round would look complete without it.
        reason = "the documented format needs the cluster name"
        self.__answer(
            [],
            unresolved=[
                {
                    "address": "aws_ecs_service.api",
                    "resource_id": "arn:aws:ecs:eu-west-1:1:service/api",
                    "reason": reason,
                }
            ],
        )

        mapping = await self.service.get_import_addresses(SELECTED_IDS)

        # No import id was built: the agent's `resource_id` is the listed
        # id it paired the block with, so it is kept as such.
        self.assertEqual(set(), mapping.imports)
        self.assertEqual(
            [
                (
                    "aws_ecs_service.api",
                    "",
                    "arn:aws:ecs:eu-west-1:1:service/api",
                    reason,
                )
            ],
            [
                (a.address, a.resource_id, a.listed_id, a.error)
                for a in mapping.unresolved
            ],
        )

    async def test_imports_keep_the_listed_id_they_were_built_from(self):
        # The import id is often a fragment of the listed id; a retry that
        # must rebuild a rejected one needs the listed id back.
        arn = "arn:aws:ec2:eu-west-1:111122223333:vpc/vpc-0123"
        self.__answer(
            [{"address": "aws_vpc.main", "resource_id": "vpc-0123", "listed_id": arn}]
        )

        mapping = await self.service.get_import_addresses([arn])

        self.assertEqual(
            [("aws_vpc.main", "vpc-0123", arn)],
            [(a.address, a.resource_id, a.listed_id) for a in mapping.imports],
        )
