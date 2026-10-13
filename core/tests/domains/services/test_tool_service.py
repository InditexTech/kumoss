# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic, reportArgumentType=false

"""An agent loop never executes the same tool call twice.

The result of an identical call is already in the conversation, so the
repeat is rejected with a message that pushes the agent to act, and a
single-use tool is withdrawn once it succeeds. Both reset when a file
operation succeeds, since the workspace may have changed.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock

from src.domains.dto import ToolCallDTO, ToolDefinitionDTO, ToolResultDTO
from src.domains.entities.tool_loop_state import ToolLoopState
from src.domains.interfaces.tool_registry_interface import IToolRegistry
from src.domains.interfaces.tracer_interface import ITracer
from src.domains.services.tool_service import ToolOrchestrationService
from src.domains.services.tracer_service import TracerService
from src.shared.constants import ToolContext


def _tool(
    name: str, single_use: bool = False, mutates_workspace: bool = False
) -> ToolDefinitionDTO:
    return ToolDefinitionDTO(
        name=name,
        description="",
        parameters={},
        context=ToolContext.WORKSPACE_INSPECTION,
        single_use=single_use,
        mutates_workspace=mutates_workspace,
    )


READ_FILE = _tool("read_file")
LIST_DIR = _tool("list_dir")
DIFF_HISTORY = _tool("diff_history", single_use=True)
WRITE_TO_FILE = _tool("write_to_file", mutates_workspace=True)
TASK_COMPLETE = _tool("task_complete")
TOOLS = [READ_FILE, LIST_DIR, DIFF_HISTORY, WRITE_TO_FILE, TASK_COMPLETE]


def _call(name: str, call_id: str, **parameters) -> ToolCallDTO:
    return ToolCallDTO(id=call_id, name=name, parameters=parameters)


def _result(call: ToolCallDTO, success: bool = True) -> ToolResultDTO:
    return ToolResultDTO(
        name=call.name, tool_call_id=call.id, success=success, result="ok"
    )


def _names(tools: list[ToolDefinitionDTO]) -> list[str]:
    return [t.name for t in tools]


class TestToolLoopState(unittest.TestCase):
    def setUp(self):
        self.state = ToolLoopState(TOOLS, TASK_COMPLETE)

    def test_explanation_does_not_make_a_call_new(self):
        first = _call("list_dir", "c1", relative_workspace_path=".", explanation="a")
        self.state.record(first, _result(first))
        reworded = _call("list_dir", "c2", relative_workspace_path=".", explanation="b")
        self.assertTrue(self.state.is_duplicate(reworded))

    def test_single_use_tool_is_withdrawn_after_success(self):
        call = _call("diff_history", "c1", explanation="x")
        self.state.record(call, _result(call))
        self.assertEqual(
            _names(self.state.available_tools()),
            ["read_file", "list_dir", "write_to_file", "task_complete"],
        )

    def test_failed_single_use_call_keeps_the_tool(self):
        call = _call("diff_history", "c1", explanation="x")
        self.state.record(call, _result(call, success=False))
        self.assertIn("diff_history", _names(self.state.available_tools()))

    def test_successful_mutation_restores_tools_and_forgets_calls(self):
        diff = _call("diff_history", "c1")
        read = _call("read_file", "c2", target_file="main.tf")
        write = _call("write_to_file", "c3", target_file="main.tf", content="x")
        for call in (diff, read, write):
            self.state.record(call, _result(call))

        self.assertEqual(_names(self.state.available_tools()), _names(TOOLS))
        self.assertFalse(self.state.is_duplicate(read))
        self.assertTrue(self.state.is_duplicate(write))

    def test_failed_mutation_changes_nothing(self):
        read = _call("read_file", "c1", target_file="main.tf")
        write = _call("write_to_file", "c2", target_file="x.txt", content="x")
        self.state.record(read, _result(read))
        self.state.record(write, _result(write, success=False))
        self.assertTrue(self.state.is_duplicate(read))

    def test_sentinel_is_never_withdrawn(self):
        sentinel = _tool("diff_history", single_use=True)
        state = ToolLoopState([sentinel], sentinel)
        call = _call("diff_history", "c1")
        state.record(call, _result(call))
        self.assertEqual(_names(state.available_tools()), ["diff_history"])


class TestDuplicateToolCalls(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tracer_token = TracerService.set_current_tracer(MagicMock(spec=ITracer))
        self.registry = MagicMock(spec=IToolRegistry)
        self.registry.validate_tool_parameters.return_value = True
        self.registry.execute_tool = AsyncMock(side_effect=_result)
        self.service = ToolOrchestrationService(self.registry)
        self.state = ToolLoopState(TOOLS, TASK_COMPLETE)

    def tearDown(self):
        TracerService.reset_current_tracer(self._tracer_token)

    async def test_identical_call_is_rejected_across_rounds(self):
        first = await self.service.execute_tool_calls(
            [_call("list_dir", "c1", relative_workspace_path=".")], self.state
        )
        repeat = await self.service.execute_tool_calls(
            [_call("list_dir", "c2", relative_workspace_path=".")], self.state
        )

        self.assertTrue(first[0].success)
        self.assertFalse(repeat[0].success)
        self.assertEqual(repeat[0].tool_call_id, "c2")
        self.assertIn("Duplicate call", repeat[0].error_message)
        self.assertEqual(self.registry.execute_tool.await_count, 1)

    async def test_different_parameters_are_not_duplicates(self):
        results = await self.service.execute_tool_calls(
            [
                _call("read_file", "c1", target_file="main.tf"),
                _call("read_file", "c2", target_file="outputs.tf"),
            ],
            self.state,
        )
        self.assertTrue(all(r.success for r in results))

    async def test_successful_write_allows_rereading(self):
        read = _call("read_file", "c1", target_file="main.tf")
        await self.service.execute_tool_calls([read], self.state)
        await self.service.execute_tool_calls(
            [_call("write_to_file", "c2", target_file="main.tf", content="x")],
            self.state,
        )
        results = await self.service.execute_tool_calls(
            [_call("read_file", "c3", target_file="main.tf")], self.state
        )
        self.assertTrue(results[0].success)

    async def test_without_loop_state_calls_always_execute(self):
        call = _call("list_dir", "c1", relative_workspace_path=".")
        await self.service.execute_tool_calls([call])
        results = await self.service.execute_tool_calls([call])
        self.assertTrue(results[0].success)


if __name__ == "__main__":
    unittest.main()
