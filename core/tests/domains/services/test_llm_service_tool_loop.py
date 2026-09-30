# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic, reportArgumentType=false

"""The tools offered to the agent shrink as the loop progresses.

A single-use tool disappears once it succeeds, and the last round of the
budget offers only the sentinel, with a notice telling the agent why, so
the loop closes with the agent's account instead of an exception.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.domains.dto import (
    LLMMetadata,
    LLMResponseDTO,
    PromptTemplateDTO,
    ToolCallDTO,
    ToolDefinitionDTO,
    ToolResultDTO,
)
from src.domains.interfaces.llm_interface import ILLMProvider
from src.domains.interfaces.tool_registry_interface import IToolRegistry
from src.domains.interfaces.tracer_interface import ITracer
from src.domains.services.llm_service import LLMOrchestrationService
from src.domains.services.tool_service import ToolOrchestrationService
from src.domains.services.tracer_service import TracerService
from src.shared.config import system_config
from src.shared.constants import PromptsLibrary, ToolContext


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
DIFF_HISTORY = _tool("diff_history", single_use=True)
TASK_COMPLETE = _tool("task_complete")
PROMPT = PromptTemplateDTO(type=PromptsLibrary.IAC_GENERATOR, prompt="system")


def _response(name: str, call_id: str, **parameters) -> LLMResponseDTO:
    return LLMResponseDTO(
        text="",
        metadata=LLMMetadata(
            input_tokens=1, output_tokens=1, finish_reason="tool_use", model="m"
        ),
        tool_calls=[ToolCallDTO(id=call_id, name=name, parameters=parameters)],
    )


def _result(call: ToolCallDTO) -> ToolResultDTO:
    return ToolResultDTO(
        name=call.name, tool_call_id=call.id, success=True, result="ok"
    )


class TestToolLoopRounds(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tracer_token = TracerService.set_current_tracer(MagicMock(spec=ITracer))
        registry = MagicMock(spec=IToolRegistry)
        registry.validate_tool_parameters.return_value = True
        registry.execute_tool = AsyncMock(side_effect=_result)
        self.llm = MagicMock(spec=ILLMProvider)
        self.service = LLMOrchestrationService(
            main_llm_provider=self.llm,
            small_llm_provider=MagicMock(spec=ILLMProvider),
            tool_service=ToolOrchestrationService(registry),
        )

    def tearDown(self):
        TracerService.reset_current_tracer(self._tracer_token)

    def _offered(self, round_index: int) -> list[str]:
        call = self.llm.inference.await_args_list[round_index]
        return [t.name for t in call.kwargs["tools"]]

    def _notice(self, round_index: int) -> str | None:
        return self.llm.inference.await_args_list[round_index].kwargs["notice"]

    async def test_single_use_tool_is_withdrawn_after_success(self):
        self.llm.inference = AsyncMock(
            side_effect=[
                _response("diff_history", "c1"),
                _response("task_complete", "c2"),
            ]
        )

        await self.service.generate(
            "q", [READ_FILE, DIFF_HISTORY], TASK_COMPLETE, PROMPT
        )

        self.assertEqual(
            self._offered(0), ["read_file", "diff_history", "task_complete"]
        )
        self.assertEqual(self._offered(1), ["read_file", "task_complete"])

    @patch.object(system_config.orchestration, "max_tool_agent_executions", 3)
    async def test_last_round_offers_only_the_sentinel(self):
        self.llm.inference = AsyncMock(
            side_effect=[
                _response("read_file", "c1", target_file="a.tf"),
                _response("read_file", "c2", target_file="b.tf"),
                _response("task_complete", "c3"),
            ]
        )

        result = await self.service.generate(
            "q", [READ_FILE, DIFF_HISTORY], TASK_COMPLETE, PROMPT
        )

        self.assertEqual(result.name, "task_complete")
        self.assertIsNone(self._notice(1))
        self.assertEqual(self._offered(2), ["task_complete"])
        notice = self._notice(2)
        assert notice is not None
        self.assertIn("`task_complete`", notice)

    @patch.object(system_config.orchestration, "max_tool_agent_executions", 1)
    async def test_no_notice_when_the_sentinel_is_the_only_tool(self):
        self.llm.inference = AsyncMock(side_effect=[_response("task_complete", "c1")])

        await self.service.generate("q", [TASK_COMPLETE], prompt=PROMPT)

        self.assertIsNone(self._notice(0))


if __name__ == "__main__":
    unittest.main()
