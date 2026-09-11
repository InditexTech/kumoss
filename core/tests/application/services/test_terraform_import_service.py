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
from src.domains.dto import TerraformValidationDTO
from src.shared.constants import TerraformProvider


def _import_result(validation: bool, feedback: str = "") -> TerraformValidationDTO:
    return TerraformValidationDTO(
        validation=validation,
        feedback=feedback,
        terraform_plan="",
        terraform_targets=[],
    )


class TestTerraformImportService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.import_prv = AsyncMock()
        self.service = TerraformImportService(import_provider=self.import_prv)

    # --- Discovery ---

    async def test_unmanaged_resources_are_the_sorted_scope_diff(self):
        self.import_prv.state_resource_ids.return_value = ["res-b"]
        self.import_prv.scope_resource_ids.return_value = ["res-c", "res-a", "res-b"]

        unmanaged = await self.service.get_unmanaged_resources(
            scope_id="scope-123",
            terraform_provider=TerraformProvider.AZURE,
        )

        self.assertEqual(unmanaged, ["res-a", "res-c"])

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
        # the caller never has to recover it from the raw validations.
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
