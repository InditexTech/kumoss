# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for TerraformImportService.

Cover the two derivations the service owns so its callers do not have to
repeat them: the unmanaged resource diff and the partition of an import
round into the resources now tracked in state and the ones Terraform
rejected.
"""

import unittest
from unittest.mock import AsyncMock

from src.application.services.terraform_import_service import TerraformImportService
from src.domains.dto import TerraformDiscoveryDTO, TerraformImportResourceDTO
from src.shared.constants import TerraformProvider


def _discovery(resource_ids: list[str], feedback: str = "") -> TerraformDiscoveryDTO:
    return TerraformDiscoveryDTO(resource_ids=resource_ids, feedback=feedback)


def _import_result(ok: bool, feedback: str = "") -> TerraformImportResourceDTO:
    return TerraformImportResourceDTO(ok=ok, stdout="", feedback=feedback)


class TestTerraformImportService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.import_prv = AsyncMock()
        self.service = TerraformImportService(import_provider=self.import_prv)

    # --- Discovery ---

    async def test_unmanaged_resources_are_the_sorted_scope_diff(self):
        self.import_prv.state_resource_ids.return_value = _discovery(["res-b"])
        self.import_prv.scope_resource_ids.return_value = _discovery(
            ["res-c", "res-a", "res-b"]
        )

        discovery = await self.service.get_unmanaged_resources(
            scope_id="scope-123",
            terraform_provider=TerraformProvider.AZURE,
        )

        self.assertEqual(discovery.resource_ids, ["res-a", "res-c"])
        self.assertEqual(discovery.feedback, "")

    async def test_failed_scope_query_reports_the_provider_diagnostics(self):
        # The three ways a round finds nothing to import stay apart: here
        # the query failed, so its stderr reaches the caller verbatim.
        self.import_prv.state_resource_ids.return_value = _discovery([])
        self.import_prv.scope_resource_ids.return_value = _discovery(
            [], "Error: invalid token"
        )

        discovery = await self.service.get_unmanaged_resources(
            scope_id="scope-123",
            terraform_provider=TerraformProvider.AZURE,
        )

        self.assertEqual(discovery.resource_ids, [])
        self.assertIn("could not be listed", discovery.feedback)
        self.assertIn("Error: invalid token", discovery.feedback)

    async def test_empty_scope_is_reported_apart_from_a_failed_query(self):
        self.import_prv.state_resource_ids.return_value = _discovery([])
        self.import_prv.scope_resource_ids.return_value = _discovery([])

        discovery = await self.service.get_unmanaged_resources(
            scope_id="scope-123",
            terraform_provider=TerraformProvider.AZURE,
        )

        self.assertEqual(discovery.resource_ids, [])
        self.assertIn("holds no importable resource", discovery.feedback)

    async def test_fully_managed_scope_is_reported_apart_from_an_empty_one(self):
        self.import_prv.state_resource_ids.return_value = _discovery(["res-a", "res-b"])
        self.import_prv.scope_resource_ids.return_value = _discovery(["res-a", "res-b"])

        discovery = await self.service.get_unmanaged_resources(
            scope_id="scope-123",
            terraform_provider=TerraformProvider.AZURE,
        )

        self.assertEqual(discovery.resource_ids, [])
        self.assertIn("already managed", discovery.feedback)

    # --- Import execution ---

    async def test_import_resources_partitions_the_round_by_result(self):
        self.import_prv.import_resource.side_effect = [
            _import_result(True),
            _import_result(False, "resource already managed"),
        ]

        outcome = await self.service.import_resources(
            [
                ("azurerm_resource_group.main", "res-1"),
                ("azurerm_storage_account.sta", "res-2"),
            ]
        )

        # The service keeps the address/resource id pairing it was given, so
        # the caller never has to recover it from the raw import results.
        self.assertEqual(
            [(a.address, a.resource_id, a.error) for a in outcome.imported],
            [("azurerm_resource_group.main", "res-1", "")],
        )
        self.assertEqual(
            [(a.address, a.resource_id, a.error) for a in outcome.failed],
            [("azurerm_storage_account.sta", "res-2", "resource already managed")],
        )
        self.assertEqual(outcome.addresses, ["azurerm_resource_group.main"])

    async def test_import_resources_with_nothing_to_import(self):
        outcome = await self.service.import_resources([])

        self.assertEqual(outcome.imported, [])
        self.assertEqual(outcome.failed, [])
        self.assertEqual(outcome.addresses, [])
        self.import_prv.import_resource.assert_not_awaited()
