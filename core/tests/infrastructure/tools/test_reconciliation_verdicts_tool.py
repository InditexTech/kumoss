# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""The reconciliation filter sentinel.

The agent itemises every change of a drift operation and flags the ones
that would undo the session, and the outcome follows from those flags:
an operation keeps its original wording when nothing is flagged, goes
away when everything is, and is replaced by the agent's rewrite when
only part of it is. A mixed verdict without that rewrite is rejected so
the agent is asked again instead of losing the genuine drift.
"""

import unittest
from typing import Any, cast

from src.domains.dto import ReconciliationReport, ToolCallDTO
from src.infrastructure.tools.tool_registry_static import ToolRegistryStatic
from src.shared.constants import ToolContext


def change(reverts: bool) -> dict[str, Any]:
    return {"description": "a change", "reverts_session_change": reverts, "reason": "r"}


class TestReconciliationVerdictsTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry = ToolRegistryStatic(llm=None)

    async def _report(self, *verdicts: dict[str, Any]):
        return await self.registry.execute_tool(
            ToolCallDTO(
                id="call_1",
                name="report_reconciliation_verdicts",
                parameters={"verdicts": list(verdicts)},
            )
        )

    def test_is_the_only_tool_of_its_context(self):
        tools = self.registry.get_available_tools(ToolContext.FILTER_RECONCILIATION)

        self.assertEqual([t.name for t in tools], ["report_reconciliation_verdicts"])

    async def test_outcome_follows_the_flags(self):
        result = await self._report(
            {"index": 1, "changes": [change(False)], "operation": "reworded"},
            {"index": 2, "changes": [change(True), change(True)]},
            {"index": 3, "changes": [change(True), change(False)], "operation": "rest"},
        )

        self.assertTrue(result.success, result.error_message)
        verdicts = cast(ReconciliationReport, result.result).verdicts
        self.assertEqual(verdicts[0].reconciled("original"), "original")
        self.assertIsNone(verdicts[1].reconciled("original"))
        self.assertEqual(verdicts[2].reconciled("original"), "rest")

    async def test_rejects_a_mixed_verdict_without_its_rewrite(self):
        result = await self._report(
            {"index": 1, "changes": [change(True), change(False)], "operation": " "}
        )

        self.assertFalse(result.success)
        self.assertIn("must hold its rewrite", result.error_message or "")

    async def test_rejects_a_verdict_without_changes(self):
        result = await self._report({"index": 1, "changes": []})

        self.assertFalse(result.success)
