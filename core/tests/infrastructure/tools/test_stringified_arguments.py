# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Models sometimes send a nested object or array argument as its JSON text.

The registry decodes it where the tool schema expects structure, so the call
succeeds on the first attempt instead of costing a regeneration, and leaves
every other string untouched.
"""

import json
import unittest
from typing import Any, cast

from src.domains.dto import TerraformPlanReport, ToolCallDTO
from src.infrastructure.tools.tool_registry_static import ToolRegistryStatic


IMPACT: dict[str, Any] = {
    "banner": {"level": "low", "title": "Low Impact", "description": "One add."},
    "summary": "Adds one storage account.",
    "bullet_points": [
        {"title": "Pins", "description": "Uses 'version = \"= 4.63.0\"'."}
    ],
}
CHANGE: dict[str, Any] = {
    "name": "Storage",
    "action": "create",
    "notes": '{"looks": "like json"}',
    "summary": "New account.",
    "details": "+ azurerm_storage_account.this",
}


class TestStringifiedArguments(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry = ToolRegistryStatic()

    async def _plan(self, **overrides: Any):
        parameters: dict[str, Any] = {
            "summary": {"create": 1, "update": 0, "delete": 0, "recreate": 0},
            "detailed_changes": [CHANGE],
            "potential_impact": IMPACT,
            "estimated_costs": {
                "currency": "USD",
                "total_fixed_monthly_cost": 0,
                "introduction_paragraph": "Approximate.",
                "breakdown": [],
            },
            **overrides,
        }
        return await self.registry.execute_tool(
            ToolCallDTO(
                id="call_1",
                name="generate_terraform_plan_report",
                parameters=parameters,
            )
        )

    async def test_a_stringified_object_is_decoded(self):
        result = await self._plan(potential_impact=json.dumps(IMPACT))

        self.assertTrue(result.success, result.error_message)
        report = cast(TerraformPlanReport, result.result)
        self.assertEqual(report.potential_impact.model_dump(), IMPACT)

    async def test_stringified_values_nested_in_arrays_are_decoded(self):
        result = await self._plan(detailed_changes=[json.dumps(CHANGE)])

        self.assertTrue(result.success, result.error_message)

    async def test_a_string_field_holding_json_stays_a_string(self):
        result = await self._plan()

        self.assertTrue(result.success, result.error_message)
        report = cast(TerraformPlanReport, result.result)
        self.assertEqual(report.detailed_changes[0].notes, CHANGE["notes"])

    async def test_text_that_is_not_the_expected_structure_still_fails(self):
        for bad in ("not json", json.dumps([IMPACT])):
            result = await self._plan(potential_impact=bad)

            self.assertFalse(result.success, bad)
