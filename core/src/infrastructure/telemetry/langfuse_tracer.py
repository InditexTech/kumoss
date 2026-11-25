# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""ITracer for Langfuse, over plain OpenTelemetry.

Spans carry Langfuse's own attributes (``langfuse.*``, plus ``session.id``
and ``user.id``) rather than a generic semantic convention, so Langfuse
reads them without guessing: observation types, chat messages, model,
usage and filterable metadata. Every span repeats the trace-level ones,
which Langfuse accepts on any span: a Terraform span can start a trace of
its own, and it must still land in its session.
"""

import dataclasses
import json
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Literal, final, override
from uuid import UUID

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace import Span, Tracer
from opentelemetry.util.types import AttributeValue
from pydantic import BaseModel

from src.domains.dto import (
    LLMMetadata,
    LLMResponseDTO,
    ToolCallDTO,
    ToolDefinitionDTO,
    ToolResultDTO,
)
from src.domains.entities.history import History
from src.domains.interfaces.tracer_interface import ITracer, TracedTerraformResult
from src.infrastructure.exceptions import TracerRootContextError
from src.infrastructure.telemetry._initializer import get_tracer
from src.shared.config import system_config
from src.shared.constants import OperationType

ObservationType = Literal["agent", "generation", "tool", "evaluator"]
Attribute = tuple[str, AttributeValue]


@final
class Attr:
    """The span attributes Langfuse maps onto traces and observations."""

    SESSION_ID = "session.id"
    USER_ID = "user.id"
    ENVIRONMENT = "langfuse.environment"
    TRACE_TAGS = "langfuse.trace.tags"
    TRACE_METADATA = "langfuse.trace.metadata"
    TYPE = "langfuse.observation.type"
    INPUT = "langfuse.observation.input"
    OUTPUT = "langfuse.observation.output"
    LEVEL = "langfuse.observation.level"
    STATUS_MESSAGE = "langfuse.observation.status_message"
    METADATA = "langfuse.observation.metadata"
    MODEL = "langfuse.observation.model.name"
    MODEL_PARAMETERS = "langfuse.observation.model.parameters"
    USAGE = "langfuse.observation.usage_details"


class LangfuseTracer(ITracer):
    def __init__(
        self,
        session_id: UUID,
        user_id: str,
        providers: Sequence[str],
        repo_uri: str,
        root_module_path: str,
        operation: OperationType,
        branch_name: str,
    ):
        """
        LangfuseTracer is tied to the lifetime of a single request or session.

        :param session_id: Langfuse session the traces are grouped under
        :param user_id: Identifier for the user associated with this session
        :param providers: Terraform provider types of the root module; empty
            on a first call, whose providers are only known once its setup
            has run
        :param operation: the session's operation, a trace tag
        :param branch_name: The name of the git's branch name where the changes are being implemented
        """
        self.__tracer: Tracer = get_tracer()
        self.__session_id: str = str(session_id)
        self.__user_id: str = user_id
        self.__operation: OperationType = operation
        self.__providers: tuple[str, ...] = tuple(providers)
        self.__repo_uri: str = repo_uri
        self.__root_module_path: str = root_module_path
        self.__branch_name: str = branch_name
        self.__root_context: Context | None = None

    def __trace_attributes(self) -> Iterator[Attribute]:
        """The trace-level attributes, repeated on every span."""
        yield Attr.SESSION_ID, self.__session_id
        yield Attr.USER_ID, self.__user_id
        yield Attr.ENVIRONMENT, system_config.environment
        yield Attr.TRACE_TAGS, (self.__operation.value, *self.__providers)
        yield from _metadata(
            Attr.TRACE_METADATA,
            {
                "operation": self.__operation.value,
                "providers": ",".join(self.__providers),
                "repo_uri": self.__repo_uri,
                "root_module_path": self.__root_module_path,
                "branch_name": self.__branch_name,
            },
        )

    def __start(
        self,
        name: str,
        attributes: Iterator[Attribute],
        context: Context | None = None,
        start_time: int | None = None,
    ) -> Span:
        span = self.__tracer.start_span(
            name=name, context=context, start_time=start_time
        )
        for key, value in (*self.__trace_attributes(), *attributes):
            span.set_attribute(key, value)
        return span

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
        return self.__start(
            # The verb names the span, so plan, drift and apply are
            # separable; the outcome boolean stays in it.
            name=f"Terraform {operation} - {terraformDTO.ok}",
            start_time=start_time,
            attributes=_chain(
                _type("evaluator"),
                _input(kwargs),
                _output(terraformDTO.summary.strip('"').strip("'")),
            ),
        )

    @override
    def trace_chain(self, **kwargs: Any) -> Span:
        """
        Creates the root span of an agent run; later LLM and tool spans are
        its children.

        :param kwargs: Keyword arguments containing the prompt, history and other parameters
        :return: OpenTelemetry Span configured with agent-specific attributes
        """
        chain_type: str = kwargs["prompt"].type.name
        span = self.__start(
            name=f"Chain - {chain_type}",
            attributes=_chain(
                _type("agent"),
                _input(kwargs["query"]),
                _metadata(Attr.METADATA, {"chain_type": chain_type}),
            ),
        )
        self.__root_context = trace.set_span_in_context(span)
        return span

    @override
    def trace_chain_output(self, span: Span, output: Any) -> Span:
        """
        Sets the chain's final return value as the output of its span.

        :param span: The span trace_chain returned
        :param output: The chain final return output
        :return: The same span
        """
        for key, value in _output(_chain_result(output)):
            span.set_attribute(key, value)
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
        Creates and configures a generation span for an LLM inference call.

        :param start_time: Start time of the LLM call in nanoseconds since epoch
        :param model: The LLM model being used (e.g., vertex_ai/claude-sonnet-4-6)
        :param invocation_params: Parameters passed to the LLM API call
        :param response: The LLM response containing text, tool calls, and metadata
        :param kwargs: Additional keyword arguments including messages, tools, and history
        :return: OpenTelemetry Span configured with generation attributes
        """
        if not self.__root_context:
            raise TracerRootContextError(
                message="Root context is not set",
                error_code=500,
            )
        model_name, llm_provider = _resolve_model(model)
        return self.__start(
            name="Async Inference",
            context=self.__root_context,
            start_time=start_time,
            attributes=_chain(
                _type("generation"),
                _input(
                    _input_messages(
                        kwargs["msg"],
                        kwargs.get("history"),
                        kwargs.get("system_prompt"),
                        kwargs.get("notice"),
                    )
                ),
                _output(_output_message(response)),
                iter(((Attr.MODEL, model_name),)),
                _model_parameters(invocation_params),
                _usage(response.metadata),
                _metadata(
                    Attr.METADATA,
                    {
                        "llm_provider": llm_provider,
                        "finish_reason": response.metadata.finish_reason,
                        "tools": _tool_definitions(kwargs.get("tools")),
                    },
                ),
            ),
        )

    @override
    def trace_tool(
        self, start_time: int, output: ToolResultDTO, *args: list[Any], **kwargs: Any
    ) -> Span:
        """
        Creates and configures a span for tracing tool operations.

        :param start_time: Start time of the tool call in nanoseconds since epoch
        :param output: The tool response output
        :param kwargs: Keyword arguments containing the tool input
        :return: OpenTelemetry Span configured with tool-specific attributes
        """
        tool: ToolCallDTO | None = kwargs.get("tool_call")
        return self.__start(
            name=f"Tool call - {tool.name if tool else 'undefined'}",
            start_time=start_time,
            context=self.__root_context,
            attributes=_chain(
                _type("tool"),
                _input(tool.parameters if tool else (kwargs or args)),
                _output(output),
                _tool_failure(output),
                _metadata(
                    Attr.METADATA,
                    {
                        "tool_name": tool.name if tool else None,
                        # Links the result back to the originating tool_call.id.
                        "tool_call_id": (
                            (output.tool_call_id or tool.id) if tool else None
                        ),
                    },
                ),
            ),
        )


def _chain(*parts: Iterator[Attribute]) -> Iterator[Attribute]:
    for part in parts:
        yield from part


def _type(kind: ObservationType) -> Iterator[Attribute]:
    yield Attr.TYPE, kind


def _serialize(payload: Any) -> str:
    """
    A payload as Langfuse reads it: strings as they are, everything else as
    JSON when possible (Langfuse renders JSON as a tree), otherwise ``str``.

    A dataclass field declared ``repr=False`` is left out: a value its own
    type keeps out of logs (a plan's text, carried along for a later
    consumer) has no business in a span either.
    """
    if isinstance(payload, str):
        return payload
    if isinstance(payload, BaseModel):
        return payload.model_dump_json()
    if dataclasses.is_dataclass(payload) and not isinstance(payload, type):
        hidden = {f.name for f in dataclasses.fields(payload) if not f.repr}
        payload = {
            key: value
            for key, value in dataclasses.asdict(payload).items()
            if key not in hidden
        }
    try:
        return json.dumps(payload, ensure_ascii=False, default=str)
    except TypeError, ValueError:
        return str(payload)


def _input(payload: Any) -> Iterator[Attribute]:
    yield Attr.INPUT, _serialize(payload)


def _output(payload: Any) -> Iterator[Attribute]:
    yield Attr.OUTPUT, _serialize(payload)


def _metadata(prefix: str, values: Mapping[str, Any]) -> Iterator[Attribute]:
    """One attribute per key, so each is filterable in Langfuse; None skipped."""
    for key, value in values.items():
        if value is not None:
            yield f"{prefix}.{key}", _serialize(value)


def _chain_result(output: Any) -> Any:
    """The part of a chain's return value worth reading: the summary of a
    tool result when it has one, otherwise the value itself."""
    if not isinstance(output, ToolResultDTO):
        return output
    result = output.result
    if isinstance(result, BaseModel):
        result = result.model_dump()
    if isinstance(result, dict):
        return (
            result.get("summary")
            or result.get("explanation")
            or result.get("description")
            or result
        )
    return result


def _tool_failure(output: Any) -> Iterator[Attribute]:
    """A failed tool call is an ERROR observation, so it stands out in the
    trace and can be filtered on."""
    if isinstance(output, ToolResultDTO) and not output.success:
        yield Attr.LEVEL, "ERROR"
        if output.error_message:
            yield Attr.STATUS_MESSAGE, output.error_message


def _resolve_model(model: str) -> tuple[str, str | None]:
    """The model name without LiteLLM's provider prefix, which is what
    Langfuse matches against its model definitions for cost, and the
    provider itself."""
    import litellm

    try:
        model_name, llm_provider, *_ = litellm.get_llm_provider(model)
    except Exception:
        return model, None
    return model_name, llm_provider


def _model_parameters(invocation_parameters: Mapping[str, Any]) -> Iterator[Attribute]:
    """
    The invocation parameters as Langfuse's flat parameter map: scalars as
    they are, anything else as JSON. Message, system prompt and tool
    payloads are not among them: they are traced as the input messages and
    the tools metadata.
    """
    params: dict[str, Any] = {}
    for key, value in invocation_parameters.items():
        if hasattr(value, "model_dump"):
            value = value.model_dump(exclude_none=True, mode="json")
        if not isinstance(value, (str, int, float, bool)) and value is not None:
            value = json.dumps(value, ensure_ascii=False, default=str)
        params[key] = value
    yield Attr.MODEL_PARAMETERS, json.dumps(params, ensure_ascii=False, default=str)


def _usage(metadata: LLMMetadata) -> Iterator[Attribute]:
    yield (
        Attr.USAGE,
        json.dumps(
            {
                "input": metadata.input_tokens,
                "output": metadata.output_tokens,
                "total": metadata.input_tokens + metadata.output_tokens,
            }
        ),
    )


def _tool_definitions(
    tools: list[ToolDefinitionDTO] | None,
) -> list[dict[str, Any]] | None:
    """The tools offered to the model, in the OpenAI function format."""
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


def _tool_call(call: ToolCallDTO) -> dict[str, Any]:
    return {
        "id": call.id,
        "type": "function",
        "function": {
            "name": call.name,
            "arguments": json.dumps(call.parameters, ensure_ascii=False, default=str),
        },
    }


def _input_messages(
    query: str | list[ToolResultDTO],
    history: History | None,
    system_prompt: str | None = None,
    notice: str | None = None,
) -> list[dict[str, Any]]:
    """
    The conversation sent to the model, as OpenAI-style chat messages,
    which Langfuse renders as a chat: system prompt, history turns (tool
    results become ``tool`` messages, tool calls an ``assistant`` message
    carrying ``tool_calls``), the query and the trailing notice.
    """

    def tool_results(results: list[ToolResultDTO]) -> list[dict[str, Any]]:
        return [
            {
                "role": "tool",
                "tool_call_id": r.tool_call_id,
                "content": str(r.result) if r.success else str(r.error_message),
            }
            for r in results
        ]

    def text(role: str, content: Any) -> dict[str, Any]:
        return {
            "role": role,
            "content": content if isinstance(content, str) else str(content),
        }

    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append(text("system", system_prompt))
    for turn in history or ():
        if isinstance(turn.user, list):
            messages.extend(tool_results(turn.user))
        else:
            messages.append(text("user", turn.user))
        if isinstance(turn.assistant, list):
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [_tool_call(t) for t in turn.assistant],
                }
            )
        else:
            messages.append(text("assistant", turn.assistant))
    if isinstance(query, list):
        messages.extend(tool_results(query))
    else:
        messages.append(text("user", query))
    if notice:
        messages.append(text("user", notice))
    return messages


def _output_message(response: LLMResponseDTO) -> dict[str, Any]:
    """The model's answer as one assistant chat message."""
    message: dict[str, Any] = {"role": "assistant", "content": response.text or None}
    if response.tool_calls:
        message["tool_calls"] = [_tool_call(t) for t in response.tool_calls]
    return message
