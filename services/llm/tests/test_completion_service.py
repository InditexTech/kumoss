# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic, reportAssignmentType=false, reportAttributeAccessIssue=false
"""The LiteLLM call, ported from the core's ``test_litellm_adapter_unit.py``.

The request-building half of the adapter (history, tool schemas, the
thinking switch) stays in the core, so what is pinned here is the half
that moved: the exact ``router.acompletion`` call, the raw fields read
off the ``ModelResponse``, the ``OpenAIError`` translation and the
provider resolution the core's tracer used. The Router is a mock
throughout; nothing reaches a provider.
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import openai
from litellm.exceptions import APIConnectionError, APIError, RateLimitError
from litellm.types.utils import (
    ChatCompletionMessageToolCall,
    Choices,
    Function,
    Message,
    ModelResponse,
    Usage,
)

from src.completion_service import CompletionService, model_name_and_provider
from src.exceptions import InferenceCallAPIError


def _service() -> tuple[CompletionService, MagicMock]:
    router = MagicMock()
    router.acompletion = AsyncMock()
    return CompletionService(router), router


def _kwargs(**extra) -> dict:
    kwargs = {
        "model": "vertex_ai/claude-sonnet-4-6",
        "messages": [
            {"role": "system", "content": "be helpful"},
            {"role": "user", "content": "hello"},
        ],
        "max_tokens": 4096,
        "temperature": 0.1,
        "num_retries": 3,
        "timeout": 600.0,
    }
    kwargs.update(extra)
    return kwargs


def _model_response(
    text: str | None = "hello",
    tool_calls: list | None = None,
    finish_reason: str = "stop",
    model: str = "claude-sonnet-4-6",
    input_tokens: int = 10,
    output_tokens: int = 20,
    usage: bool = True,
    **message_fields,
) -> ModelResponse:
    response = ModelResponse(
        model=model,
        choices=[
            Choices(
                index=0,
                message=Message(
                    content=text,
                    role="assistant",
                    tool_calls=tool_calls,
                    **message_fields,
                ),
                finish_reason=finish_reason,
            )
        ],
        usage=Usage(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
    )
    if not usage:
        del response.usage
    return response


class TestRouterCall(unittest.IsolatedAsyncioTestCase):
    async def test_kwargs_are_forwarded_verbatim_with_drop_params(self):
        service, router = _service()
        router.acompletion.return_value = _model_response()

        await service.complete(_kwargs())

        router.acompletion.assert_awaited_once_with(**_kwargs(), drop_params=True)

    async def test_tool_and_thinking_keys_are_forwarded_when_present(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                },
            }
        ]
        service, router = _service()
        router.acompletion.return_value = _model_response()

        await service.complete(_kwargs(tools=tools, tool_choice="auto"))
        self.assertEqual(router.acompletion.call_args.kwargs["tools"], tools)
        self.assertEqual(router.acompletion.call_args.kwargs["tool_choice"], "auto")
        self.assertNotIn("reasoning_effort", router.acompletion.call_args.kwargs)

        await service.complete(_kwargs(temperature=1.0, reasoning_effort="low"))
        call = router.acompletion.call_args.kwargs
        self.assertEqual(call["reasoning_effort"], "low")
        self.assertEqual(call["temperature"], 1.0)
        self.assertNotIn("tools", call)
        self.assertNotIn("tool_choice", call)

    async def test_configured_timeout_is_sent(self):
        service, router = _service()
        router.acompletion.return_value = _model_response()

        await service.complete(_kwargs(timeout=42.0))

        self.assertEqual(router.acompletion.call_args.kwargs["timeout"], 42.0)


class TestResponseFields(unittest.IsolatedAsyncioTestCase):
    async def test_plain_text_reply(self):
        service, router = _service()
        router.acompletion.return_value = _model_response(text="hi there")

        result = await service.complete(_kwargs())

        self.assertEqual(result.text, "hi there")
        self.assertEqual(result.finish_reason, "stop")
        self.assertEqual(result.model, "claude-sonnet-4-6")
        self.assertEqual(result.prompt_tokens, 10)
        self.assertEqual(result.completion_tokens, 20)
        self.assertEqual(result.tool_calls, [])
        self.assertIsNone(result.reasoning_content)

    async def test_finish_reason_is_raw(self):
        # Mapping (`stop` -> `end_turn`, ...) is the core's job.
        for reason in ("stop", "length", "tool_calls", "content_filter"):
            with self.subTest(reason=reason):
                service, router = _service()
                router.acompletion.return_value = _model_response(finish_reason=reason)
                result = await service.complete(_kwargs())
                self.assertEqual(result.finish_reason, reason)

    async def test_null_content_reads_as_empty_text(self):
        service, router = _service()
        router.acompletion.return_value = _model_response(text=None)

        result = await service.complete(_kwargs())

        self.assertEqual(result.text, "")

    async def test_missing_usage_reads_as_zero_tokens(self):
        service, router = _service()
        router.acompletion.return_value = _model_response(usage=False)

        result = await service.complete(_kwargs())

        self.assertEqual((result.prompt_tokens, result.completion_tokens), (0, 0))

    async def test_tool_calls_carry_the_raw_arguments_string(self):
        arguments = json.dumps({"query": "vault", "include_pattern": "*.tf"})
        tc = ChatCompletionMessageToolCall(
            id="call_abc",
            type="function",
            function=Function(name="grep_search", arguments=arguments),
        )
        service, router = _service()
        router.acompletion.return_value = _model_response(
            text="", tool_calls=[tc], finish_reason="tool_calls"
        )

        result = await service.complete(_kwargs())

        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(result.tool_calls[0].id, "call_abc")
        self.assertEqual(result.tool_calls[0].name, "grep_search")
        self.assertEqual(result.tool_calls[0].arguments, arguments)
        self.assertEqual(result.finish_reason, "tool_calls")

    async def test_reasoning_content_is_returned_when_present(self):
        service, router = _service()
        router.acompletion.return_value = _model_response(
            reasoning_content="let me think"
        )

        result = await service.complete(_kwargs(reasoning_effort="low"))

        self.assertEqual(result.reasoning_content, "let me think")

    async def test_provider_is_resolved_from_the_requested_model(self):
        service, router = _service()
        router.acompletion.return_value = _model_response()

        result = await service.complete(_kwargs(model="anthropic/claude-sonnet-5"))

        self.assertEqual(result.model_name, "claude-sonnet-5")
        self.assertEqual(result.llm_provider, "anthropic")


class TestModelNameAndProvider(unittest.TestCase):
    def test_resolves_provider_prefixed_models(self):
        self.assertEqual(
            model_name_and_provider("vertex_ai/claude-sonnet-4-6"),
            ("claude-sonnet-4-6", "vertex_ai"),
        )

    def test_unresolvable_models_read_as_nulls(self):
        # A `model_list` alias such as "main" is not a LiteLLM model id.
        self.assertEqual(model_name_and_provider("main"), (None, None))

    def test_any_exception_reads_as_nulls(self):
        with patch(
            "src.completion_service.litellm.get_llm_provider",
            side_effect=RuntimeError("boom"),
        ):
            self.assertEqual(model_name_and_provider("openai/gpt-4o"), (None, None))


class TestApiErrors(unittest.IsolatedAsyncioTestCase):
    async def test_api_error_raises_inference_call_error_with_its_status(self):
        service, router = _service()
        router.acompletion.side_effect = APIError(
            message="service unavailable",
            model="claude-sonnet-4-6",
            llm_provider="vertex_ai",
            status_code=503,
        )

        with self.assertLogs("src.logger._logger", level="ERROR") as logs:
            with self.assertRaises(InferenceCallAPIError) as ctx:
                await service.complete(_kwargs())

        self.assertEqual(ctx.exception.error_code, 503)
        self.assertEqual(
            ctx.exception.message,
            "Inference call to vertex_ai/claude-sonnet-4-6 failed.",
        )
        # `{e!r}`: LiteLLM exceptions define their own repr.
        self.assertIn(
            f"LiteLLM API error: {router.acompletion.side_effect!r}",
            "".join(logs.output),
        )

    async def test_rate_limit_keeps_429(self):
        service, router = _service()
        router.acompletion.side_effect = RateLimitError(
            message="slow down", llm_provider="openai", model="gpt-4o"
        )

        with self.assertRaises(InferenceCallAPIError) as ctx:
            await service.complete(_kwargs())

        self.assertEqual(ctx.exception.error_code, 429)

    async def test_litellm_connection_error_keeps_its_status(self):
        service, router = _service()
        error = APIConnectionError(
            message="refused", llm_provider="openai", model="gpt-4o"
        )
        router.acompletion.side_effect = error

        with self.assertRaises(InferenceCallAPIError) as ctx:
            await service.complete(_kwargs())

        self.assertEqual(ctx.exception.error_code, error.status_code)

    async def test_an_openai_error_without_status_defaults_to_502(self):
        service, router = _service()
        router.acompletion.side_effect = openai.OpenAIError("no status here")

        with self.assertRaises(InferenceCallAPIError) as ctx:
            await service.complete(_kwargs())

        self.assertEqual(ctx.exception.error_code, 502)

    async def test_other_exceptions_propagate(self):
        service, router = _service()
        router.acompletion.side_effect = ValueError("not an API error")

        with self.assertRaises(ValueError):
            await service.complete(_kwargs())


if __name__ == "__main__":
    unittest.main()
