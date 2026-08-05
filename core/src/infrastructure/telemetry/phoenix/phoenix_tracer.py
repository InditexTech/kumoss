# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import json
from collections.abc import Iterator
from typing import Any, override
from uuid import UUID

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace import Tracer, Span

from openinference.semconv.trace import (
    OpenInferenceMimeTypeValues,
    OpenInferenceSpanKindValues,
    SpanAttributes,
)

from src.domains.dto import (
    TerraformValidationDTO,
    ToolResultDTO,
    ToolCallDTO,
)
from src.domains.interfaces.tracer_interface import ITracer
from src.infrastructure.telemetry._initializer import get_tracer
from src.shared.constants import TerraformProvider


class PhoenixTracer(ITracer):
    def __init__(
        self,
        session_id: UUID,
        user_id: str,
        cloud: TerraformProvider,
        iac_path: str,
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
        self.__session_id: str = str(session_id)
        self.__user_id: str = user_id
        self.__terraform_prv: TerraformProvider = cloud
        self.__iac_path: str = iac_path
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
                    "cloud": self.__terraform_prv.name,
                    "iac_path": self.__iac_path,
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
        for attribute_key, attribute_value in (*_output_attributes(output),):
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
        if tool and tool.name == "task_complete":
            output = output.result.get("final_summary")
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
