# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

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
    OpenInferenceLLMProviderValues,
    OpenInferenceLLMSystemValues,
    SpanAttributes,
    ToolAttributes,
    ToolCallAttributes,
)

from src.domains.dto import (
    TerraformValidationDTO,
    ToolResultDTO,
    LLMResponseDTO,
    ToolCallDTO,
    LLMMetadata,
    ToolDefinitionDTO,
)
from src.domains.entities.history import History
from src.domains.interfaces.tracer_interface import ITracer
from src.infrastructure.telemetry._initializer import get_tracer
from src.infrastructure.exceptions import (
    TracerRootContextError,
    ProviderOpenInferenceNotFound,
)
from src.shared.constants import LLMProvider


class PhoenixTracer(ITracer):
    def __init__(
        self,
        session_id: UUID,
        user_id: str,
        project: str,
        branch_name: str | None = None,
    ):
        """
        PhoenixTracer implements a concrete adapter to OTel for a Phoenix collector
        This class is tied with the lifetime of a single request or session.

        :param session_id: Unique identifier for this tracing session
        :param user_id: Identifier for the user associated with this session
        :param project: The name of the selected project
        :param branch_name: The name of the git's branch name where the changes are being implemented
        """
        self.__tracer: Tracer = get_tracer()
        self.__session_id: str = session_id.hex
        self.__user_id: str = user_id
        self.__project: str = project
        self.__branch_name: str = branch_name if branch_name else "undefined"
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
                    "project": self.__project,
                    "branch_name": self.__branch_name,
                    **kwargs,
                }
            ),
        )

    @override
    def trace_terraform(
        self, terraformDTO: TerraformValidationDTO, **kwargs: Any
    ) -> Span:
        """
        Creates and configures a span for tracing Terraform operations.

        :param terraformDTO: TerraformValidationDTO with all the goodies
        :return OpenTelemetry Span configured with evaluator-specific attirbutes
        """
        span = self.__tracer.start_span(
            name=f"Terraform - validation {terraformDTO.validation}"
        )
        for attribute_key, attribute_value in (
            *self.__metadata_attributes(),
            *_span_kind_attributes(OpenInferenceSpanKindValues.EVALUATOR),
            *_input_attributes(kwargs),
            *_output_attributes(
                terraformDTO.terraform_plan.strip('"').strip("'")
                if terraformDTO.validation
                else terraformDTO.feedback.strip('"').strip("'")
            ),
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
            *_span_kind_attributes(OpenInferenceSpanKindValues.CHAIN),
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
        for attribute_key, attribute_value in (*_output_attributes(output),):
            span.set_attribute(attribute_key, attribute_value)
        return span

    @override
    def trace_llm(
        self,
        start_time: int,
        provider: LLMProvider,
        invocation_params: Any,
        response: LLMResponseDTO,
        **kwargs: Any,
    ) -> Span:
        """
        Creates and configures a span for tracing LLM inference calls.

        :param start_time: Start time of the LLM call in nanoseconds since epoch
        :param provider: The LLM provider being used (e.g., Anthropic, Google)
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
            *_input_attributes(kwargs),
            *_span_kind_attributes(OpenInferenceSpanKindValues.LLM),
            *_llm_model_name_attributes(provider),
            *_llm_invocation_parameters_attributes(invocation_params),
            *_llm_input_messages_attributes(kwargs["msg"], kwargs.get("history")),
            *_llm_tools(kwargs.get("tools")),
            *_output_llm_attributes(response),
            *_llm_output_message_attributes(response),
            *_llm_token_usage_attributes(response.metadata),
        ):
            span.set_attribute(attribute_key, attribute_value)

        return span

    @override
    def trace_tool(
        self, start_time: int, output: Any, *args: list[Any], **kwargs: Any
    ) -> Span:
        """
        Creates and configures a span for tracing tool operations.

        :param start_time: Start time of the LLM call in nanoseconds since epoch
        :param output: The tool response output
        :param kwargs: Keyword arguments containing the tool input
        :return: OpenTelemetry Span configured with tool-specific attributes
        """
        tool_name: ToolCallDTO | None = kwargs.get("tool_call")
        span = self.__tracer.start_span(
            name=f"Tool call - {tool_name.name if tool_name else 'undefined'}",
            start_time=start_time,
            context=self.__root_context,
        )
        for attribute_key, attribute_value in (
            *self.__metadata_attributes(),
            *_span_kind_attributes(OpenInferenceSpanKindValues.TOOL),
            *_input_attributes(kwargs or args),
            *_output_attributes(output),
        ):
            span.set_attribute(attribute_key, attribute_value)
        return span


def _input_attributes(payload: Any) -> Iterator[tuple[str, str]]:
    """
    Yields the OpenInference input value attribute as a JSON string if the
    payload can be serialized as JSON, otherwise as a string.
    """
    yield SpanAttributes.INPUT_VALUE, str(payload)
    yield SpanAttributes.INPUT_MIME_TYPE, OpenInferenceMimeTypeValues.TEXT.value


def _output_attributes(payload: Any) -> Iterator[tuple[str, str]]:
    """
    Yields the OpenInference output value attribute as a JSON string if the
    payload can be serialized as JSON, otherwise as a string.
    """
    yield SpanAttributes.OUTPUT_VALUE, str(payload)
    yield SpanAttributes.OUTPUT_MIME_TYPE, OpenInferenceMimeTypeValues.TEXT.value


def _span_kind_attributes(
    kind: OpenInferenceSpanKindValues,
) -> Iterator[tuple[str, str]]:
    """
    Yields the OpenInference span kind attribute for LLMs.
    """
    yield SpanAttributes.OPENINFERENCE_SPAN_KIND, kind.value


def _llm_model_name_attributes(provider_name: LLMProvider) -> Iterator[tuple[str, str]]:
    """
    Maps provider name to OpenInference value and yields the OpenInference model name attribute.
    """
    if any(key in provider_name.name.lower() for key in ["opus", "sonnet", "haiku"]):
        if "sonnet" in provider_name.name.lower():
            model_name = "claude-sonnet-4-5-20250929"
        elif "haiku" in provider_name.name.lower():
            model_name = "claude-haiku-4-5-20251001"
        elif "opus" in provider_name.name.lower():
            model_name = "claude-opus-4-1"
        else:
            model_name = "undefined"
        provider = OpenInferenceLLMProviderValues.ANTHROPIC.value
        system = OpenInferenceLLMSystemValues.ANTHROPIC.value
    elif "gemini" in provider_name.name.lower():
        if "lite" in provider_name.name.lower():
            model_name = "gemini-2.5-flash-lite"
        elif "flash" in provider_name.name.lower():
            model_name = "gemini-3-flash-preview"
        elif "pro" in provider_name.name.lower():
            model_name = "gemini-3-pro-preview"
        else:
            model_name = "undefined"
        provider = OpenInferenceLLMProviderValues.GOOGLE.value
        system = OpenInferenceLLMSystemValues.VERTEXAI.value
    else:
        raise ProviderOpenInferenceNotFound(
            message=f"Provider {provider_name.name} couldn't be mapped to OpenInference",
            error_code=404,
        )
    yield SpanAttributes.LLM_MODEL_NAME, model_name
    yield SpanAttributes.LLM_PROVIDER, provider
    yield SpanAttributes.LLM_SYSTEM, system


def _llm_invocation_parameters_attributes(
    invocation_parameters: dict[str, Any],
) -> Iterator[tuple[str, str]]:
    """
    Yields the OpenInference invocation parameters attribute as a JSON string.
    """
    for k, v in invocation_parameters.items():
        if not isinstance(v, (int | str | float | bool | None)):
            invocation_parameters[k] = str(v)
    yield (
        SpanAttributes.LLM_INVOCATION_PARAMETERS,
        json.dumps(obj=invocation_parameters, ensure_ascii=False),
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
) -> Iterator[tuple[str, str]]:
    """
    Yields the OpenInference input messages attributes for each message in the list.
    """

    def _trace_tool_result(
        tool_result: ToolResultDTO, idx: int
    ) -> Iterator[tuple[str, str]]:
        yield (
            f"{SpanAttributes.LLM_INPUT_MESSAGES}.{idx}.{MessageAttributes.MESSAGE_TOOL_CALLS}.0."
            + f"{ToolCallAttributes.TOOL_CALL_ID}",
            tool_result.tool_call_id,
        )
        yield (
            f"{SpanAttributes.LLM_INPUT_MESSAGES}.{idx}.{MessageAttributes.MESSAGE_CONTENT}",
            str(tool_result.result)
            if tool_result.result
            else str(tool_result.error_message),
        )
        yield (
            f"{SpanAttributes.LLM_INPUT_MESSAGES}.{idx}.{MessageAttributes.MESSAGE_ROLE}",
            "user",
        )

    def _trace_tool_call(tool_call: ToolCallDTO, idx: int) -> Iterator[tuple[str, str]]:
        yield (
            f"{SpanAttributes.LLM_INPUT_MESSAGES}.{idx}.{MessageAttributes.MESSAGE_TOOL_CALLS}.0."
            + f"{ToolCallAttributes.TOOL_CALL_ID}",
            tool_call.id,
        )
        yield (
            f"{SpanAttributes.LLM_INPUT_MESSAGES}.{idx}.{MessageAttributes.MESSAGE_TOOL_CALLS}.0."
            + f"{ToolCallAttributes.TOOL_CALL_FUNCTION_NAME}",
            tool_call.name,
        )
        yield (
            f"{SpanAttributes.LLM_INPUT_MESSAGES}.{idx}.{MessageAttributes.MESSAGE_TOOL_CALLS}.0."
            + f"{ToolCallAttributes.TOOL_CALL_FUNCTION_ARGUMENTS_JSON}",
            json.dumps(tool_call.parameters),
        )
        yield (
            f"{SpanAttributes.LLM_INPUT_MESSAGES}.{idx}.{MessageAttributes.MESSAGE_ROLE}",
            "assistant",
        )

    def _trace_text_msg(
        msg: str, role: Literal["user", "assistant"], idx: int
    ) -> Iterator[tuple[str, str]]:
        yield (
            f"{SpanAttributes.LLM_INPUT_MESSAGES}.{idx}.{MessageAttributes.MESSAGE_CONTENT}",
            msg,
        )
        yield (
            f"{SpanAttributes.LLM_INPUT_MESSAGES}.{idx}.{MessageAttributes.MESSAGE_ROLE}",
            role,
        )

    idx = 0
    if history:
        for turn in history:
            if isinstance(turn.user, list) and isinstance(turn.user[0], ToolResultDTO):
                yield from _trace_tool_result(turn.user[0], idx)
            else:
                yield from _trace_text_msg(turn.user, "user", idx)
            idx += 1
            if isinstance(turn.assistant, list) and isinstance(
                turn.assistant[0], ToolCallDTO
            ):
                yield from _trace_tool_call(turn.assistant[0], idx)
            else:
                yield from _trace_text_msg(turn.assistant, "assistant", idx)
            idx += 1
    if isinstance(query, list) and isinstance(query[0], ToolResultDTO):
        yield from _trace_tool_result(query[0], idx)
    else:
        yield from _trace_text_msg(query, "user", idx)


def _output_llm_attributes(response: LLMResponseDTO) -> Iterator[tuple[str, str]]:
    """
    Yields the OpenInference output value attribute as a JSON string for tool calls,
    or as plain text for text responses, along with the appropriate MIME type.
    """
    if response.text:
        yield SpanAttributes.OUTPUT_VALUE, response.text
        yield SpanAttributes.OUTPUT_MIME_TYPE, OpenInferenceMimeTypeValues.TEXT.value
    elif response.tool_calls:
        yield (
            SpanAttributes.OUTPUT_VALUE,
            json.dumps([tc.__dict__ for tc in response.tool_calls]),
        )
        yield SpanAttributes.OUTPUT_MIME_TYPE, OpenInferenceMimeTypeValues.JSON.value


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
        idx = 0
        for tool in response.tool_calls:
            yield (
                f"{SpanAttributes.LLM_OUTPUT_MESSAGES}.0.{MessageAttributes.MESSAGE_TOOL_CALLS}.{idx}."
                + f"{ToolCallAttributes.TOOL_CALL_FUNCTION_NAME}",
                tool.name,
            )
            # summary = tool.parameters.get("final_summary")
            # explanation = tool.parameters.get("explanation")
            yield (
                f"{SpanAttributes.LLM_OUTPUT_MESSAGES}.0.{MessageAttributes.MESSAGE_TOOL_CALLS}.{idx}."
                + f"{ToolCallAttributes.TOOL_CALL_FUNCTION_ARGUMENTS_JSON}",
                # json.dumps(tool.parameters) if not (summary or explanation) else (summary or explanation)
                json.dumps(tool.parameters),
            )
            idx += 1


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
