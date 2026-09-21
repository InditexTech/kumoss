# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from src.domains.services.task_service import TaskService
from src.shared.config import system_config
from src.shared.constants import PromptsLibrary, ToolContext


class TestTaskService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.group_size = system_config.orchestration.drift_group_operations
        self.llm_svc = AsyncMock()
        self.template_svc = AsyncMock()
        self.template_svc.render.return_value = "rendered prompt"
        self.tool_svc = MagicMock()
        self.tool_svc.get_available_tools.return_value = ["tools"]
        self.tool_svc.get_sentinel_tool.return_value = "sentinel"
        self.service = TaskService(
            llm_service=self.llm_svc,
            template_service=self.template_svc,
            tool_service=self.tool_svc,
        )

    def _ops(self, count: int) -> list[str]:
        return [f"op-{i}" for i in range(count)]

    def _llm_returns(self, operations: list[str]) -> None:
        self.llm_svc.generate.return_value = MagicMock(
            result={"operations": operations}
        )

    async def test_split_task_groups_operations_by_configured_size(self):
        ops = self._ops(self.group_size + 1)
        self._llm_returns(ops)

        groups = await self.service.split_task(task="drift report")

        self.assertEqual(groups, [ops[: self.group_size], ops[self.group_size :]])
        self.template_svc.render.assert_awaited_once_with(PromptsLibrary.TASK_SPLITTER)
        self.tool_svc.get_available_tools.assert_called_once_with(
            contexts=[
                ToolContext.WORKSPACE_INSPECTION,
                ToolContext.EXTERNAL_INFORMATION,
            ]
        )

    async def test_filter_reconciliation_sends_flat_json_and_regroups(self):
        kept = self._ops(self.group_size + 2)
        self._llm_returns(kept)
        incoming = [["a", "b"], ["c"]]

        groups = await self.service.filter_reconciliation(operations=incoming)

        self.assertEqual(groups, [kept[: self.group_size], kept[self.group_size :]])
        kwargs = self.llm_svc.generate.await_args.kwargs
        self.assertEqual(json.loads(kwargs["query"]), ["a", "b", "c"])
        self.assertEqual(kwargs["prompt"], "rendered prompt")
        self.assertEqual(kwargs["sentinel_tool"], "sentinel")
        self.template_svc.render.assert_awaited_once_with(
            PromptsLibrary.FILTER_RECONCILIATION
        )
        self.tool_svc.get_available_tools.assert_called_once_with(
            ToolContext.WORKSPACE_INSPECTION
        )
        self.tool_svc.get_sentinel_tool.assert_called_once_with(
            ToolContext.TASK_SPLITTER
        )

    async def test_filter_reconciliation_returns_empty_when_everything_filtered(self):
        self._llm_returns([])

        groups = await self.service.filter_reconciliation(operations=[["a"]])

        self.assertEqual(groups, [])

    async def test_filter_reconciliation_skips_llm_when_nothing_to_filter(self):
        groups = await self.service.filter_reconciliation(operations=[])

        self.assertEqual(groups, [])
        self.llm_svc.generate.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
