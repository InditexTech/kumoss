# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""The drift report sentinel and its two optional blocks, and the import
report's excluded resources.

`unreconciled_drift` and `whitelisted_exceptions` are what the round
left in place, so a round that left nothing behind must produce a report
with neither, and a report that carries them must keep them apart: drift
an exception rule covers was not a failure. The same holds for the
resources the import exception list withheld.
"""

import unittest
from typing import Any, cast

from src.domains.dto import TerraformDriftReport, TerraformImportReport, ToolCallDTO
from src.infrastructure.tools.tool_registry_static import ToolRegistryStatic
from src.shared.constants import ToolContext


REMEDIATED: list[dict[str, Any]] = [
    {
        "file_path": "key_vault.tf",
        "resource_address": "azurerm_key_vault.kvt_001",
        "changes": [
            {
                "attribute_modified": "network_acls",
                "change_description": "Added the IP rule 203.0.113.10/32.",
                "reason": "The rule was added in the portal.",
            }
        ],
    }
]


class TestDriftReportTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry = ToolRegistryStatic(llm=None)

    async def _report(self, **parameters: Any) -> TerraformDriftReport:
        result = await self.registry.execute_tool(
            ToolCallDTO(
                id="call_1",
                name="generate_terraform_drift_report",
                parameters={
                    "summary": "One resource reconciled.",
                    "status": "Succeeded",
                    "remediated_resources": REMEDIATED,
                    **parameters,
                },
            )
        )

        self.assertTrue(result.success, result.error_message)
        return cast(TerraformDriftReport, result.result)

    def test_the_optional_blocks_are_not_required_parameters(self):
        self.assertTrue(
            self.registry.validate_tool_parameters(
                "generate_terraform_drift_report",
                {
                    "summary": "One resource reconciled.",
                    "status": "Succeeded",
                    "remediated_resources": REMEDIATED,
                },
            )
        )

    def test_the_optional_blocks_are_offered_to_the_model(self):
        drift_tool = next(
            tool
            for tool in self.registry.get_available_tools(ToolContext.REPORT_GENERATOR)
            if tool.name == "generate_terraform_drift_report"
        )
        properties = drift_tool.parameters["properties"]

        self.assertIn("unreconciled_drift", properties)
        self.assertIn("whitelisted_exceptions", properties)
        self.assertNotIn("unreconciled_drift", drift_tool.parameters["required"])
        self.assertNotIn("whitelisted_exceptions", drift_tool.parameters["required"])

    async def test_a_clean_round_reports_neither_block(self):
        report = await self._report()

        self.assertEqual(report.unreconciled_drift, [])
        self.assertEqual(report.whitelisted_exceptions, [])

    async def test_both_blocks_reach_the_report(self):
        report = await self._report(
            status="Partial",
            unreconciled_drift=[
                {
                    "resource_address": "azurerm_redis_cache.rds_001",
                    "reason": "The iteration limit was reached.",
                    "details": ["The sku_name still differs."],
                }
            ],
            whitelisted_exceptions=[
                {
                    "resource_address": "azurerm_storage_account.sta_001",
                    "change": "The created_at tag differs.",
                    "rule": "The provider reports a permanent false diff on it.",
                }
            ],
        )

        self.assertEqual(
            report.unreconciled_drift[0].resource_address,
            "azurerm_redis_cache.rds_001",
        )
        self.assertEqual(
            report.unreconciled_drift[0].details, ["The sku_name still differs."]
        )
        self.assertEqual(
            report.whitelisted_exceptions[0].rule,
            "The provider reports a permanent false diff on it.",
        )

    async def test_unreconciled_drift_needs_no_resource_address(self):
        # A drift read that failed names no resource: the reason is all there is.
        report = await self._report(
            status="Failed",
            remediated_resources=[],
            unreconciled_drift=[{"reason": "The plan could not be read."}],
        )

        self.assertEqual(report.unreconciled_drift[0].resource_address, "")
        self.assertEqual(report.unreconciled_drift[0].details, [])


IMPORTED: list[dict[str, Any]] = [
    {
        "resource_address": "azurerm_storage_account.sta_001",
        "resource_id": "/subscriptions/s/resourceGroups/rg/providers/"
        + "Microsoft.Storage/storageAccounts/sta001",
        "status": "imported",
        "details": "Storage account sta001.",
    }
]


class TestImportReportTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry = ToolRegistryStatic(llm=None)

    async def _report(self, **parameters: Any) -> TerraformImportReport:
        result = await self.registry.execute_tool(
            ToolCallDTO(
                id="call_1",
                name="generate_terraform_import_report",
                parameters={
                    "summary": {"selected": 1, "imported": 1, "failed": 0},
                    "status": "Succeeded",
                    "execution_summary": "One storage account is now managed.",
                    "imported_resources": IMPORTED,
                    "excluded_resources": [],
                    "state_alignment": "No changes.",
                    "recommendations": [],
                    **parameters,
                },
            )
        )

        self.assertTrue(result.success, result.error_message)
        return cast(TerraformImportReport, result.result)

    def test_excluded_resources_are_required_of_the_model(self):
        import_tool = next(
            tool
            for tool in self.registry.get_available_tools(ToolContext.REPORT_GENERATOR)
            if tool.name == "generate_terraform_import_report"
        )

        self.assertIn("excluded_resources", import_tool.parameters["properties"])
        self.assertIn("excluded_resources", import_tool.parameters["required"])

    async def test_excluded_resources_reach_the_report(self):
        withheld = "/subscriptions/s/resourceGroups/rg-shared-platform"
        report = await self._report(
            excluded_resources=[
                {"resource_id": withheld, "details": "Shared platform group."}
            ]
        )

        self.assertEqual(report.excluded_resources[0].resource_id, withheld)
        self.assertEqual(report.excluded_resources[0].details, "Shared platform group.")
        self.assertEqual(len(report.imported_resources), 1)

    async def test_a_round_with_nothing_withheld_reports_an_empty_block(self):
        report = await self._report(excluded_resources=[])

        self.assertEqual(report.excluded_resources, [])


if __name__ == "__main__":
    unittest.main()
