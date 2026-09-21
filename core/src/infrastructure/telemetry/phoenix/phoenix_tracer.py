# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import dataclasses
import json
from collections.abc import Iterator
from typing import Any, Literal, override
from uuid import UUID

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace import Tracer, Span

from openinference.semconv.trace import (
    MessageAttributes,
    OpenInferenceMimeTypeValues,
    OpenInferenceSpanKindValues,
    SpanAttributes,
    ToolAttributes,
    ToolCallAttributes,
)
from pydantic import BaseModel

from src.domains.dto import (
    ToolResultDTO,
    LLMResponseDTO,
    ToolCallDTO,
    LLMMetadata,
    ToolDefinitionDTO,
)
from src.domains.entities.history import History
from src.domains.interfaces.tracer_interface import ITracer, TracedTerraformResult
from src.infrastructure.telemetry._initializer import get_tracer
from src.infrastructure.exceptions import TracerRootContextError
from src.shared.constants import OperationType, TerraformProvider


class PhoenixTracer(ITracer):
    def __init__(
        self,
        session_id: UUID,
        user_id: str,
        cloud: TerraformProvider,
        repo_uri: str,
        iac_path: str,
        operation: OperationType,
        branch_name: str,
    ):
        """
        PhoenixTracer implements a concrete adapter to OTel for a Phoenix collector
        This class is tied with the lifetime of a single request or session.

        :param session_id: Unique identifier for this tracing session
        :param user_id: Identifier for the user associated with this session
        :param project: The Phoenix project traces are sent to
        :param branch_name: The name of the git's branch name where the changes are being implemented
        """
        self.__tracer: Tracer = get_tracer(operation)
        self.__session_id: str = str(session_id)
        self.__user_id: str = user_id
        self.__terraform_prv: TerraformProvider = cloud
        self.__repo_uri: str = repo_uri
        self.__iac_path: str = iac_path
        self.__branch_name: str = branch_name
        self.__root_context: Context | None = None

    def __metadata_attributes(
        self, **kwargs: dict[Any, Any]
    ) -> Iterator[tuple[str, str | dict[str, str]]]:
        """
        Retrieves session and user metadata attributes.

        :return: Iterator of tuples containing attribute key-value pairs for session and user identification
        """
        yield SpanAttributes.SESSION_ID, self.__session_id
        yield SpanAttributes.USER_ID, self.__user_id
        yield (
            SpanAttributes.METADATA,
            json.dumps(
                {
                    "session_id": self.__session_id,
                    "user_id": self.__user_id,
                    "cloud": self.__terraform_prv.name,
                    "repo_uri": self.__repo_uri,
                    "iac_path": self.__iac_path,
                    "branch_name": self.__branch_name,
                    **kwargs,
                }
            ),
        )

    @override
    def trace_terraform(
        self,
        terraformDTO: TracedTerraformResult,
        operation: str,
        start_time: int | None = None,
        **kwargs: Any,
    ) -> Span:
        """
        Creates and configures a span for tracing Terraform operations.

        :param terraformDTO: the plan, drift or apply result being traced
        :param operation: the verb that produced it, for the span name
        :param start_time: Start time of the validation in nanoseconds since epoch
        :return OpenTelemetry Span configured with evaluator-specific attirbutes
        """
        span = self.__tracer.start_span(
            name=f"Terraform {operation} - {terraformDTO.ok}",
            start_time=start_time,
        )
        for attribute_key, attribute_value in (
            *self.__metadata_attributes(),
            *_span_kind_attributes(OpenInferenceSpanKindValues.EVALUATOR),
            *_input_attributes(kwargs),
            *_output_attributes(terraformDTO.summary.strip('"').strip("'")),
        ):
            span.set_attribute(attribute_key, attribute_value)
        return span

    @override
    def trace_chain(self, **kwargs: Any) -> Span:
        """
        Creates and configures a span for tracing chain operations.

        :param kwargs: Keyword arguments containing the prompt, history and other parameters
        :return: OpenTelemetry Span configured with chain-specific attributes
        """
        span = self.__tracer.start_span(name=f"Chain - {kwargs['prompt'].type.name}")
        self.__root_context = trace.set_span_in_context(span)
        for attribute_key, attribute_value in (
            *self.__metadata_attributes(chain_type=kwargs["prompt"].type.name),
            *_span_kind_attributes(OpenInferenceSpanKindValues.AGENT),
            *_input_attributes(kwargs["query"]),
        ):
            span.set_attribute(attribute_key, attribute_value)
        return span

    @override
    def trace_chain_output(self, span: Span, output: Any) -> Span:
        """
        Creates and configures a span for tracing chain operations.

        :param kwargs: Keyword arguments containing the prompt, history and other parameters
        :return: OpenTelemetry Span configured with chain-specific attributes
        """
        for attribute_key, attribute_value in (*_output_attributes(output, True),):
            span.set_attribute(attribute_key, attribute_value)
        return span

    @override
    def trace_llm(
        self,
        start_time: int,
        model: str,
        invocation_params: Any,
        response: LLMResponseDTO,
        **kwargs: Any,
    ) -> Span:
        """
        Creates and configures a span for tracing LLM inference calls.

        :param start_time: Start time of the LLM call in nanoseconds since epoch
        :param model: The LLM model being used (e.g., vertex_ai/claude-sonnet-4-6)
        :param invocation_params: Parameters passed to the LLM API call
        :param response: The LLM response containing text, tool calls, and metadata
        :param kwargs: Additional keyword arguments including messages, tools, and history
        :return: OpenTelemetry Span configured with LLM-specific attributes
        """
        if not self.__root_context:
            raise TracerRootContextError(
                message="Root context is not set",
                error_code=500,
            )
        span = self.__tracer.start_span(
            name="Async Inference",
            context=self.__root_context if self.__root_context else None,
            start_time=start_time,
        )
        for attribute_key, attribute_value in (
            *self.__metadata_attributes(),
            *_input_attributes(kwargs["msg"]),
            *_span_kind_attributes(OpenInferenceSpanKindValues.LLM),
            *_llm_model_name_attributes(model),
            *_llm_invocation_parameters_attributes(invocation_params),
            *_llm_input_messages_attributes(
                kwargs["msg"], kwargs.get("history"), kwargs.get("system_prompt")
            ),
            *_llm_tools(kwargs.get("tools")),
            *_output_llm_attributes(response),
            *_llm_output_message_attributes(response),
            *_llm_token_usage_attributes(response.metadata),
        ):
            span.set_attribute(attribute_key, attribute_value)

        return span

    @override
    def trace_tool(
        self, start_time: int, output: ToolResultDTO, *args: list[Any], **kwargs: Any
    ) -> Span:
        """
        Creates and configures a span for tracing tool operations.

        :param start_time: Start time of the LLM call in nanoseconds since epoch
        :param output: The tool response output
        :param kwargs: Keyword arguments containing the tool input
        :return: OpenTelemetry Span configured with tool-specific attributes
        """
        tool: ToolCallDTO | None = kwargs.get("tool_call")
        span = self.__tracer.start_span(
            name=f"Tool call - {tool.name if tool else 'undefined'}",
            start_time=start_time,
            context=self.__root_context,
        )
        for attribute_key, attribute_value in (
            *self.__metadata_attributes(),
            *_span_kind_attributes(OpenInferenceSpanKindValues.TOOL),
            *_tool_attributes(tool, output),
            *_input_attributes(tool.parameters if tool else (kwargs or args)),
            *_output_attributes(output),
        ):
            span.set_attribute(attribute_key, attribute_value)
        return span


def _serialize(payload: Any) -> tuple[str, str]:
    """
    Serializes a payload to a JSON string with JSON mime type when possible,
    otherwise to a plain string with text mime type.

    A dataclass field declared ``repr=False`` is left out: a value its own
    type keeps out of logs (a plan's text, carried along for a later
    consumer) has no business in a span either.
    """
    if isinstance(payload, str):
        return payload, OpenInferenceMimeTypeValues.TEXT.value
    if isinstance(payload, BaseModel):
        return payload.model_dump_json(), OpenInferenceMimeTypeValues.JSON.value
    if dataclasses.is_dataclass(payload):
        hidden = {f.name for f in dataclasses.fields(payload) if not f.repr}
        payload = {
            key: value
            for key, value in dataclasses.asdict(payload).items()
            if key not in hidden
        }
    try:
        return (
            json.dumps(payload, ensure_ascii=False, default=str),
            OpenInferenceMimeTypeValues.JSON.value,
        )
    except (TypeError, ValueError):
        return str(payload), OpenInferenceMimeTypeValues.TEXT.value


def _input_attributes(payload: Any) -> Iterator[tuple[str, str]]:
    """
    Yields the OpenInference input value attribute as a JSON string if the
    payload can be serialized as JSON, otherwise as a string.
    """
    value, mime_type = _serialize(payload)
    yield SpanAttributes.INPUT_VALUE, value
    yield SpanAttributes.INPUT_MIME_TYPE, mime_type


def _output_attributes(
    payload: Any, filter_md: bool = False
) -> Iterator[tuple[str, str]]:
    """
    Yields the OpenInference output value attribute as a JSON string if the
    payload can be serialized as JSON, otherwise as a string.
    """
    if filter_md and isinstance(payload, ToolResultDTO):
        payload = payload.result
        if isinstance(payload, BaseModel):
            payload = payload.model_dump()
        if isinstance(payload, dict):
            payload = (
                payload.get("summary")
                or payload.get("explanation")
                or payload.get("description")
                or payload
            )
    value, mime_type = _serialize(payload)
    yield SpanAttributes.OUTPUT_VALUE, value
    yield SpanAttributes.OUTPUT_MIME_TYPE, mime_type


def _tool_attributes(
    tool_call: ToolCallDTO | None, output: ToolResultDTO
) -> Iterator[tuple[str, str]]:
    """
    Yields the OpenInference tool attributes for a TOOL span: the tool name,
    the result id (tool.id links back to the originating tool_call.id) and
    the call parameters as a JSON string.
    """
    if not tool_call:
        return
    yield SpanAttributes.TOOL_NAME, tool_call.name
    yield SpanAttributes.TOOL_ID, output.tool_call_id or tool_call.id
    yield (
        SpanAttributes.TOOL_PARAMETERS,
        json.dumps(tool_call.parameters, ensure_ascii=False, default=str),
    )


def _span_kind_attributes(
    kind: OpenInferenceSpanKindValues,
) -> Iterator[tuple[str, str]]:
    """
    Yields the OpenInference span kind attribute for LLMs.
    """
    yield SpanAttributes.OPENINFERENCE_SPAN_KIND, kind.value


_LITELLM_TO_OI_PROVIDER: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "cohere": "cohere",
    "mistral": "mistralai",
    "vertex_ai": "google",
    "vertex_ai_beta": "google",
    "gemini": "google",
    "azure": "azure",
    "azure_ai": "azure",
    "bedrock": "aws",
    "sagemaker": "aws",
    "xai": "xai",
    "deepseek": "deepseek",
    "groq": "groq",
    "fireworks_ai": "fireworks",
    "moonshot": "moonshot",
    "cerebras": "cerebras",
    "perplexity": "perplexity",
    "together_ai": "together",
}


def _llm_model_name_attributes(model: str) -> Iterator[tuple[str, str]]:
    """
    Resolves provider from a litellm model string using litellm.get_llm_provider(),
    mirroring the approach of openinference-instrumentation-litellm.
    """
    import litellm

    try:
        model_name, llm_provider, *_ = litellm.get_llm_provider(model)
    except Exception:
        yield SpanAttributes.LLM_MODEL_NAME, model
        return

    yield SpanAttributes.LLM_MODEL_NAME, model_name
    oi_provider = _LITELLM_TO_OI_PROVIDER.get(llm_provider)
    if oi_provider:
        yield SpanAttributes.LLM_PROVIDER, oi_provider


def _llm_invocation_parameters_attributes(
    invocation_parameters: dict[str, Any],
) -> Iterator[tuple[str, str]]:
    """
    Yields the OpenInference invocation parameters attribute as a JSON string.
    Message, system prompt and tool payloads are excluded: they are already
    traced as dedicated llm.input_messages / llm.tools attributes.
    """
    params: dict[str, Any] = {}
    for k, v in invocation_parameters.items():
        if hasattr(v, "model_dump"):
            v = {
                ck: cv
                for ck, cv in v.model_dump(exclude_none=True, mode="json").items()
            }
        params[k] = v
    yield (
        SpanAttributes.LLM_INVOCATION_PARAMETERS,
        json.dumps(obj=params, ensure_ascii=False, default=str),
    )


def _llm_tools(tools: list[ToolDefinitionDTO]) -> Iterator[tuple[str, str]]:
    """
    Yields the OpenInference tool calls as JSON schemas for each tool available to the LLM.
    """
    if not tools:
        return
    for idx, t in enumerate(tools):
        yield (
            f"{SpanAttributes.LLM_TOOLS}.{idx}.{ToolAttributes.TOOL_JSON_SCHEMA}",
            json.dumps(
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                }
            ),
        )


def _llm_input_messages_attributes(
    query: str | list[ToolResultDTO],
    history: History | None,
    system_prompt: str | None = None,
) -> Iterator[tuple[str, str]]:
    """
    Yields the OpenInference input messages attributes for each message in the list.
    """

    def _trace_tool_results(
        tool_results: list[ToolResultDTO], msg_idx: int
    ) -> Iterator[tuple[str, str]]:
        for i, t in enumerate(tool_results):
            yield (
                f"{SpanAttributes.LLM_INPUT_MESSAGES}.{msg_idx + i}.{MessageAttributes.MESSAGE_ROLE}",
                "tool",
            )
            yield (
                f"{SpanAttributes.LLM_INPUT_MESSAGES}.{msg_idx + i}.{MessageAttributes.MESSAGE_TOOL_CALL_ID}",
                t.tool_call_id,
            )
            yield (
                f"{SpanAttributes.LLM_INPUT_MESSAGES}.{msg_idx + i}.{MessageAttributes.MESSAGE_CONTENT}",
                str(t.result) if t.success else str(t.error_message),
            )

    def _trace_tool_calls(
        tool_calls: list[ToolCallDTO], msg_idx: int
    ) -> Iterator[tuple[str, str]]:
        yield (
            f"{SpanAttributes.LLM_INPUT_MESSAGES}.{msg_idx}.{MessageAttributes.MESSAGE_ROLE}",
            "assistant",
        )
        for i, t in enumerate(tool_calls):
            yield (
                f"{SpanAttributes.LLM_INPUT_MESSAGES}.{msg_idx}.{MessageAttributes.MESSAGE_TOOL_CALLS}.{i}."
                + f"{ToolCallAttributes.TOOL_CALL_ID}",
                t.id,
            )
            yield (
                f"{SpanAttributes.LLM_INPUT_MESSAGES}.{msg_idx}.{MessageAttributes.MESSAGE_TOOL_CALLS}.{i}."
                + f"{ToolCallAttributes.TOOL_CALL_FUNCTION_NAME}",
                t.name,
            )
            yield (
                f"{SpanAttributes.LLM_INPUT_MESSAGES}.{msg_idx}.{MessageAttributes.MESSAGE_TOOL_CALLS}.{i}."
                + f"{ToolCallAttributes.TOOL_CALL_FUNCTION_ARGUMENTS_JSON}",
                json.dumps(t.parameters),
            )

    def _trace_text_msg(
        msg: str, role: Literal["system", "user", "assistant"], idx: int
    ) -> Iterator[tuple[str, str]]:
        yield (
            f"{SpanAttributes.LLM_INPUT_MESSAGES}.{idx}.{MessageAttributes.MESSAGE_CONTENT}",
            msg if isinstance(msg, str) else str(msg),
        )
        yield (
            f"{SpanAttributes.LLM_INPUT_MESSAGES}.{idx}.{MessageAttributes.MESSAGE_ROLE}",
            role,
        )

    idx = 0
    if system_prompt:
        yield from _trace_text_msg(system_prompt, "system", idx)
        idx += 1
    if history:
        for turn in history:
            if isinstance(turn.user, list):
                yield from _trace_tool_results(turn.user, idx)
                idx += len(turn.user)
            else:
                yield from _trace_text_msg(turn.user, "user", idx)
                idx += 1
            if isinstance(turn.assistant, list):
                yield from _trace_tool_calls(turn.assistant, idx)
            else:
                yield from _trace_text_msg(turn.assistant, "assistant", idx)
            idx += 1
    if isinstance(query, list):
        yield from _trace_tool_results(query, idx)
    else:
        yield from _trace_text_msg(query, "user", idx)


def _output_llm_attributes(response: LLMResponseDTO) -> Iterator[tuple[str, str]]:
    """
    Yields the OpenInference output value attribute as a JSON string for tool calls,
    or as plain text for text responses, along with the appropriate MIME type.
    """
    if response.tool_calls:
        tool_calls = [tc.__dict__ for tc in response.tool_calls]
        yield (
            SpanAttributes.OUTPUT_VALUE,
            json.dumps(
                {"text": response.text, "tool_calls": tool_calls}
                if response.text
                else tool_calls
            ),
        )
        yield SpanAttributes.OUTPUT_MIME_TYPE, OpenInferenceMimeTypeValues.JSON.value
    else:
        yield SpanAttributes.OUTPUT_VALUE, response.text
        yield SpanAttributes.OUTPUT_MIME_TYPE, OpenInferenceMimeTypeValues.TEXT.value


def _llm_output_message_attributes(
    response: LLMResponseDTO,
) -> Iterator[tuple[str, str]]:
    """
    Yields the OpenInference output message attributes.
    """
    if response.text:
        yield (
            f"{SpanAttributes.LLM_OUTPUT_MESSAGES}.0.{MessageAttributes.MESSAGE_ROLE}",
            "assistant",
        )
        yield (
            f"{SpanAttributes.LLM_OUTPUT_MESSAGES}.0.{MessageAttributes.MESSAGE_CONTENT}",
            response.text,
        )
    if response.tool_calls:
        yield (
            f"{SpanAttributes.LLM_OUTPUT_MESSAGES}.0.{MessageAttributes.MESSAGE_ROLE}",
            "assistant",
        )
        for idx, tool in enumerate(response.tool_calls):
            yield (
                f"{SpanAttributes.LLM_OUTPUT_MESSAGES}.0.{MessageAttributes.MESSAGE_TOOL_CALLS}.{idx}."
                + f"{ToolCallAttributes.TOOL_CALL_ID}",
                tool.id,
            )
            yield (
                f"{SpanAttributes.LLM_OUTPUT_MESSAGES}.0.{MessageAttributes.MESSAGE_TOOL_CALLS}.{idx}."
                + f"{ToolCallAttributes.TOOL_CALL_FUNCTION_NAME}",
                tool.name,
            )
            yield (
                f"{SpanAttributes.LLM_OUTPUT_MESSAGES}.0.{MessageAttributes.MESSAGE_TOOL_CALLS}.{idx}."
                + f"{ToolCallAttributes.TOOL_CALL_FUNCTION_ARGUMENTS_JSON}",
                json.dumps(tool.parameters),
            )


def _llm_token_usage_attributes(
    metadata: LLMMetadata,
) -> Iterator[tuple[str, int]]:
    """
    Parses and yields token usage attributes from the response data.
    """
    yield SpanAttributes.LLM_TOKEN_COUNT_PROMPT, metadata.input_tokens
    yield SpanAttributes.LLM_TOKEN_COUNT_COMPLETION, metadata.output_tokens
    yield (
        SpanAttributes.LLM_TOKEN_COUNT_TOTAL,
        metadata.input_tokens + metadata.output_tokens,
    )
