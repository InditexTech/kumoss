# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic, reportAssignmentType=false, reportAttributeAccessIssue=false
import json
import unittest
from unittest.mock import patch, AsyncMock, MagicMock

from opentelemetry.trace import Span

from litellm.types.utils import (
    ModelResponse,
    Choices,
    Message,
    Usage,
    ChatCompletionMessageToolCall,
    Function,
)
from litellm.exceptions import APIError

from src.domains.dto import (
    LLMResponseDTO,
    ToolDefinitionDTO,
    ToolCallDTO,
    ToolResultDTO,
)
from src.domains.entities.history import History
from src.domains.interfaces.tracer_interface import ITracer
from src.domains.services.tracer_service import TracerService
from src.infrastructure.llm._litellm import LiteLLMAdapter
from src.infrastructure.exceptions import (
    InferenceCallAPIError,
    InferenceCallThinkingToolError,
    InferenceCallWebSearchTools,
)
from src.shared.constants import ToolContext


def _make_adapter(**overrides) -> tuple[LiteLLMAdapter, MagicMock]:
    router = MagicMock()
    router.acompletion = AsyncMock()
    router.aresponses = AsyncMock()
    defaults = dict(
        model="vertex_ai/claude-sonnet-4-6",
        temperature=0.1,
        max_tokens=4096,
        router=router,
    )
    defaults.update(overrides)
    return LiteLLMAdapter(**defaults), router


def _model_response(
    text: str = "hello",
    tool_calls: list | None = None,
    finish_reason: str = "stop",
    model: str = "claude-sonnet-4-6",
    input_tokens: int = 10,
    output_tokens: int = 20,
) -> ModelResponse:
    return ModelResponse(
        model=model,
        choices=[
            Choices(
                index=0,
                message=Message(content=text, role="assistant", tool_calls=tool_calls),
                finish_reason=finish_reason,
            )
        ],
        usage=Usage(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
    )


def _setup_mock_tracer(test_case):
    mock_tracer = MagicMock(spec=ITracer)
    mock_span = MagicMock(spec=Span)
    mock_tracer.trace_llm.return_value = mock_span
    test_case._tracer_token = TracerService.set_current_tracer(mock_tracer)
    test_case._mock_tracer = mock_tracer


def _teardown_mock_tracer(test_case):
    TracerService.reset_current_tracer(test_case._tracer_token)


class TestInferencePlainText(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _setup_mock_tracer(self)

    def tearDown(self):
        _teardown_mock_tracer(self)

    async def test_returns_llm_response_dto(self):
        adapter, router = _make_adapter()
        router.acompletion.return_value = _model_response(text="hi there")

        result = await adapter.inference(msg="hello", system_prompt="be helpful")

        self.assertIsInstance(result, LLMResponseDTO)
        self.assertEqual(result.text, "hi there")
        self.assertEqual(result.metadata.finish_reason, "end_turn")
        self.assertEqual(result.metadata.input_tokens, 10)
        self.assertEqual(result.metadata.output_tokens, 20)
        self.assertEqual(result.tool_calls, [])
        self.assertIsNone(result.thinking)

    async def test_messages_include_system_prompt(self):
        adapter, router = _make_adapter()
        router.acompletion.return_value = _model_response()

        await adapter.inference(msg="hi", system_prompt="be concise")

        call_kwargs = router.acompletion.call_args[1]
        messages = call_kwargs["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[0]["content"], "be concise")
        self.assertEqual(messages[-1]["role"], "user")
        self.assertEqual(messages[-1]["content"], "hi")

    async def test_no_system_prompt(self):
        adapter, router = _make_adapter()
        router.acompletion.return_value = _model_response()

        await adapter.inference(msg="hi")

        call_kwargs = router.acompletion.call_args[1]
        messages = call_kwargs["messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "user")


class TestInferenceWithTools(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _setup_mock_tracer(self)

    def tearDown(self):
        _teardown_mock_tracer(self)

    async def test_tool_calls_parsed_correctly(self):
        tc = ChatCompletionMessageToolCall(
            id="call_abc",
            type="function",
            function=Function(
                name="grep_search",
                arguments=json.dumps({"query": "vault", "include_pattern": "*.tf"}),
            ),
        )
        adapter, router = _make_adapter()
        router.acompletion.return_value = _model_response(
            text="", tool_calls=[tc], finish_reason="tool_calls"
        )

        tool_def = ToolDefinitionDTO(
            name="grep_search",
            description="Search files",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            context=ToolContext.WORKSPACE_INSPECTION,
        )
        result = await adapter.inference(msg="find vault references", tools=[tool_def])

        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0].name, "grep_search")
        self.assertEqual(result.tool_calls[0].id, "call_abc")
        self.assertEqual(result.tool_calls[0].parameters["query"], "vault")
        self.assertEqual(result.metadata.finish_reason, "tool_use")

    async def test_tools_formatted_in_openai_format(self):
        adapter, router = _make_adapter()
        router.acompletion.return_value = _model_response()

        tool_def = ToolDefinitionDTO(
            name="read_file",
            description="Read a file",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
            context=ToolContext.WORKSPACE_INSPECTION,
        )
        await adapter.inference(msg="read main.tf", tools=[tool_def])

        call_kwargs = router.acompletion.call_args[1]
        self.assertIn("tools", call_kwargs)
        self.assertEqual(call_kwargs["tools"][0]["type"], "function")
        self.assertEqual(call_kwargs["tools"][0]["function"]["name"], "read_file")
        self.assertEqual(call_kwargs["tool_choice"], "required")


class TestInferenceWithHistory(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _setup_mock_tracer(self)

    def tearDown(self):
        _teardown_mock_tracer(self)

    async def test_history_turns_included_in_messages(self):
        adapter, router = _make_adapter()
        router.acompletion.return_value = _model_response()

        history = History()
        history.append_turn(user_msg="first question", assistant_msg="first answer")
        history.append_turn(user_msg="second question", assistant_msg="second answer")

        await adapter.inference(msg="third question", history=history)

        call_kwargs = router.acompletion.call_args[1]
        messages = call_kwargs["messages"]
        # 2 turns (4 messages) + final user message = 5
        self.assertEqual(len(messages), 5)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"], "first question")
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[1]["content"], "first answer")
        self.assertEqual(messages[-1]["role"], "user")
        self.assertEqual(messages[-1]["content"], "third question")

    async def test_history_with_tool_calls(self):
        adapter, router = _make_adapter()
        router.acompletion.return_value = _model_response()

        tool_calls = [
            ToolCallDTO(id="call_1", name="grep_search", parameters={"q": "test"})
        ]
        tool_results = [
            ToolResultDTO(
                name="grep_search",
                tool_call_id="call_1",
                success=True,
                result="found it",
            )
        ]

        history = History()
        history.append_turn(user_msg="search for test", assistant_msg=tool_calls)

        await adapter.inference(msg=tool_results, history=history)

        call_kwargs = router.acompletion.call_args[1]
        messages = call_kwargs["messages"]
        # user msg + assistant tool_calls msg + tool result msg = 3
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertIn("tool_calls", messages[1])
        self.assertEqual(messages[2]["role"], "tool")


class TestInferenceThinking(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _setup_mock_tracer(self)

    def tearDown(self):
        _teardown_mock_tracer(self)

    async def test_thinking_sets_reasoning_effort_and_temperature(self):
        adapter, router = _make_adapter()
        router.acompletion.return_value = _model_response()

        await adapter.inference(msg="think hard", thinking=True)

        call_kwargs = router.acompletion.call_args[1]
        self.assertEqual(call_kwargs["reasoning_effort"], "medium")
        self.assertEqual(call_kwargs["temperature"], 1.0)

    async def test_thinking_with_tools_raises(self):
        adapter, _ = _make_adapter()
        tool_def = ToolDefinitionDTO(
            name="test",
            description="test",
            parameters={},
            context=ToolContext.WORKSPACE_INSPECTION,
        )
        with self.assertRaises(InferenceCallThinkingToolError):
            await adapter.inference(msg="test", tools=[tool_def], thinking=True)


class TestInferenceWebSearch(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _setup_mock_tracer(self)

    def tearDown(self):
        _teardown_mock_tracer(self)

    @patch("src.infrastructure.llm._litellm.litellm.get_model_info")
    async def test_native_web_search_passes_options(self, mock_model_info):
        mock_model_info.return_value = {
            "supported_openai_params": ["web_search_options"]
        }
        adapter, router = _make_adapter(model="gemini/gemini-2.5-flash")
        router.acompletion.return_value = _model_response()

        await adapter.inference(msg="latest news", web_search=True)

        call_kwargs = router.acompletion.call_args[1]
        self.assertIn("web_search_options", call_kwargs)
        self.assertEqual(
            call_kwargs["web_search_options"]["search_context_size"], "medium"
        )

    @patch("src.infrastructure.llm._litellm.litellm.get_model_info")
    async def test_fallback_web_search_calls_aresponses(self, mock_model_info):
        mock_model_info.return_value = {"supported_openai_params": []}

        content_block = MagicMock()
        content_block.text = "search result"
        output_item = MagicMock()
        output_item.content = [content_block]
        mock_resp = MagicMock()
        mock_resp.output = [output_item]
        mock_resp.model = "openai/gpt-5"
        mock_usage = MagicMock()
        mock_usage.input_tokens = 5
        mock_usage.output_tokens = 15
        mock_usage.total_tokens = 20
        mock_resp.usage = mock_usage

        adapter, router = _make_adapter(model="openai/gpt-5")
        router.aresponses.return_value = mock_resp

        result = await adapter.inference(msg="search something", web_search=True)

        router.aresponses.assert_awaited_once()
        self.assertEqual(result.text, "search result")

    async def test_web_search_with_tools_raises(self):
        adapter, _ = _make_adapter()
        tool_def = ToolDefinitionDTO(
            name="test",
            description="test",
            parameters={},
            context=ToolContext.WORKSPACE_INSPECTION,
        )
        with self.assertRaises(InferenceCallWebSearchTools):
            await adapter.inference(msg="test", tools=[tool_def], web_search=True)

    async def test_web_search_with_thinking_raises(self):
        adapter, _ = _make_adapter()
        with self.assertRaises(InferenceCallThinkingToolError):
            await adapter.inference(msg="test", thinking=True, web_search=True)


class TestInferenceAPIError(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _setup_mock_tracer(self)

    def tearDown(self):
        _teardown_mock_tracer(self)

    async def test_api_error_raises_inference_call_error(self):
        adapter, router = _make_adapter()
        router.acompletion.side_effect = APIError(
            message="service unavailable",
            model="claude-sonnet-4-6",
            llm_provider="vertex_ai",
            status_code=503,
        )

        with self.assertRaises(InferenceCallAPIError):
            await adapter.inference(msg="hello")


class TestStopReasonMapping(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _setup_mock_tracer(self)

    def tearDown(self):
        _teardown_mock_tracer(self)

    async def test_stop_maps_to_end_turn(self):
        adapter, router = _make_adapter()
        router.acompletion.return_value = _model_response(finish_reason="stop")
        result = await adapter.inference(msg="hi")
        self.assertEqual(result.metadata.finish_reason, "end_turn")

    async def test_length_maps_to_max_tokens(self):
        adapter, router = _make_adapter()
        router.acompletion.return_value = _model_response(finish_reason="length")
        result = await adapter.inference(msg="hi")
        self.assertEqual(result.metadata.finish_reason, "max_tokens")

    async def test_tool_calls_maps_to_tool_use(self):
        adapter, router = _make_adapter()
        router.acompletion.return_value = _model_response(finish_reason="tool_calls")
        result = await adapter.inference(msg="hi")
        self.assertEqual(result.metadata.finish_reason, "tool_use")


if __name__ == "__main__":
    unittest.main()
