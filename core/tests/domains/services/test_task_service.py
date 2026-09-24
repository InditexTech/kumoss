# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from src.domains.services.task_service import TaskService
from src.domains.value_objects import Conventions
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

    async def test_filter_exceptions_sends_flat_json_and_regroups_survivors(self):
        kept = self._ops(self.group_size + 2)
        self._llm_returns(kept)
        incoming = [["a", "b"], ["c"]]

        result = await self.service.filter_exceptions(operations=incoming)

        self.assertEqual(
            result.kept, [kept[: self.group_size], kept[self.group_size :]]
        )
        kwargs = self.llm_svc.generate.await_args.kwargs
        self.assertEqual(json.loads(kwargs["query"]), ["a", "b", "c"])
        self.assertEqual(kwargs["prompt"], "rendered prompt")
        # A text-only agent: the sentinel is the whole tool set, and
        # generate() treats a lone tool as its own sentinel.
        self.assertEqual(kwargs["tools"], ["sentinel"])
        self.assertNotIn("sentinel_tool", kwargs)
        self.template_svc.render.assert_awaited_once_with(
            PromptsLibrary.FILTER_DRIFT_EXCEPTIONS
        )
        self.tool_svc.get_sentinel_tool.assert_called_once_with(
            ToolContext.TASK_SPLITTER
        )
        self.tool_svc.get_available_tools.assert_not_called()

    async def test_filter_exceptions_reports_the_input_minus_the_survivors(self):
        self._llm_returns(["a", "c"])

        result = await self.service.filter_exceptions(operations=[["a", "b"], ["c"]])

        self.assertEqual(result.kept, [["a", "c"]])
        self.assertEqual(result.excluded, ["b"])

    async def test_filter_exceptions_counts_a_trimmed_operation_as_excluded(self):
        # A trimmed survivor no longer matches its input string, so the
        # original shows up as excluded and its remainder as kept. That is
        # precise enough for the log line the caller writes.
        self._llm_returns(["a (trimmed)"])

        result = await self.service.filter_exceptions(operations=[["a"]])

        self.assertEqual(result.kept, [["a (trimmed)"]])
        self.assertEqual(result.excluded, ["a"])

    async def test_filter_exceptions_carries_the_explanation(self):
        self.llm_svc.generate.return_value = MagicMock(
            result={"operations": ["a"], "explanation": "rule 2 covers b"}
        )

        result = await self.service.filter_exceptions(operations=[["a", "b"]])

        self.assertEqual(result.explanation, "rule 2 covers b")

    async def test_filter_exceptions_skips_llm_when_nothing_to_filter(self):
        result = await self.service.filter_exceptions(operations=[])

        self.assertEqual(result.kept, [])
        self.assertEqual(result.excluded, [])
        self.assertEqual(result.explanation, "")
        self.llm_svc.generate.assert_not_awaited()

    async def test_filter_exceptions_excludes_everything_when_nothing_survives(self):
        self._llm_returns([])

        result = await self.service.filter_exceptions(operations=[["a"], ["b"]])

        self.assertEqual(result.kept, [])
        self.assertEqual(result.excluded, ["a", "b"])

    async def test_filter_imports_renders_the_scope_and_the_conventions(self):
        self._llm_returns(["res-1"])
        history = MagicMock()

        result = await self.service.filter_imports(
            query="import the database",
            unmanaged_ids=["res-1", "res-2"],
            conventions=Conventions(templates=["tpl_a"], abbreviations=["abbr_a"]),
            history=history,
        )

        self.assertEqual(result.selected, ["res-1"])
        kwargs = self.llm_svc.generate.await_args.kwargs
        self.assertEqual(kwargs["query"], "import the database")
        self.assertEqual(kwargs["prompt"], "rendered prompt")
        self.assertIs(kwargs["history"], history)
        # A text-only agent, like the drift exception filter: the sentinel
        # is the whole tool set and is never duplicated as a kwarg.
        self.assertEqual(kwargs["tools"], ["sentinel"])
        self.assertNotIn("sentinel_tool", kwargs)
        self.tool_svc.get_sentinel_tool.assert_called_once_with(
            ToolContext.TASK_SPLITTER
        )
        self.tool_svc.get_available_tools.assert_not_called()
        # The agent matches a request phrased in the repository's vocabulary
        # against ids that carry none of it, so both reach the prompt.
        self.template_svc.render.assert_awaited_once_with(
            prompt=PromptsLibrary.IMPORT_FILTER,
            unmanaged_ids=["res-1", "res-2"],
            resources=["tpl_a"],
            abbreviations=["abbr_a"],
        )

    async def test_filter_imports_keeps_the_selection_flat(self):
        # Imports run one resource at a time, so unlike the other filters
        # here the selection is never grouped.
        ids = self._ops(self.group_size + 2)
        self._llm_returns(ids)

        result = await self.service.filter_imports(
            query="import everything",
            unmanaged_ids=ids,
            conventions=Conventions(templates=[], abbreviations=[]),
            history=MagicMock(),
        )

        self.assertEqual(result.selected, ids)

    async def test_filter_imports_carries_the_explanation(self):
        self.llm_svc.generate.return_value = MagicMock(
            result={"operations": [], "explanation": "no resource matches the request"}
        )

        result = await self.service.filter_imports(
            query="import the database",
            unmanaged_ids=["res-1"],
            conventions=Conventions(templates=[], abbreviations=[]),
            history=MagicMock(),
        )

        self.assertEqual(result.selected, [])
        self.assertEqual(result.explanation, "no resource matches the request")

    async def test_filter_imports_skips_llm_when_the_scope_holds_nothing(self):
        result = await self.service.filter_imports(
            query="import the database",
            unmanaged_ids=[],
            conventions=Conventions(templates=[], abbreviations=[]),
            history=MagicMock(),
        )

        self.assertEqual(result.selected, [])
        self.assertEqual(result.explanation, "")
        self.llm_svc.generate.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
