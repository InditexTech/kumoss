# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic
"""The intent check sentinel.

It returns the intent check's half of a compliance check only: no verdict
of its own, and findings always labelled as the intent check's, so the
model cannot pass one off as the policy engine's.
"""

import unittest
from typing import cast

from src.domains.dto import IntentCheck, ToolCallDTO
from src.infrastructure.tools.tool_registry_static import ToolRegistryStatic
from src.shared.constants import ToolContext


class TestIntentFindingsTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry = ToolRegistryStatic()

    def test_is_the_only_tool_of_its_context(self):
        tools = self.registry.get_available_tools(ToolContext.INTENT_CHECK)

        self.assertEqual([t.name for t in tools], ["report_intent_findings"])

    async def test_findings_are_the_intent_checks_whatever_the_model_says(self):
        result = await self.registry.execute_tool(
            ToolCallDTO(
                id="call_1",
                name="report_intent_findings",
                parameters={
                    "violations": [
                        {
                            "rule_id": "scope_exceeded",
                            "severity": "error",
                            "resource": "a.b",
                            "message": "not requested",
                            "source": "opa",
                        }
                    ],
                    "summary": "One change was not requested.",
                    "checked_rules": ["scope_exceeded", "scope_incomplete"],
                },
            )
        )

        self.assertTrue(result.success, result.error_message)
        intent = cast(IntentCheck, result.result)
        self.assertIsInstance(intent, IntentCheck)
        self.assertEqual(intent.violations[0].source, "intent")
        self.assertEqual(intent.checked_rules, ["scope_exceeded", "scope_incomplete"])


if __name__ == "__main__":
    unittest.main()
