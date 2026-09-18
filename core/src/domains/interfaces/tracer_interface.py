# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Any, Protocol

from abc import ABC, abstractmethod
from opentelemetry.trace import Span

from src.domains.dto import LLMResponseDTO


class TracedTerraformResult(Protocol):
    """What a terraform result exposes to the tracer, whichever verb produced it.

    Each result type decides its own traced output, so the tracer does not
    have to encode which field of which DTO means what.
    """

    @property
    def ok(self) -> bool:
        """Whether the operation reached its intended outcome."""
        ...

    @property
    def summary(self) -> str:
        """The text worth tracing: the plan on success, the problem otherwise."""
        ...


class ITracer(ABC):
    @abstractmethod
    def trace_terraform(
        self,
        terraformDTO: TracedTerraformResult,
        start_time: int | None = None,
        **kwargs: Any,
    ) -> Span:
        """
        Creates and configures a span for tracing Terraform operations.

        :param terraformDTO: the plan, drift or apply result being traced
        :param start_time: Start time of the validation in nanoseconds since epoch
        :return OpenTelemetry Span configured with evaluator-specific attirbutes
        """

    @abstractmethod
    def trace_chain(self, **kwargs) -> Span:
        """
        Creates and configures a span for tracing agent operations.

        :param kwargs: Keyword arguments containing agent prompt and other parameters
        :return: OpenTelemetry Span configured with agent-specific attributes
        """

    @abstractmethod
    def trace_chain_output(self, span: Span, output: Any) -> Span:
        """
        Includes the output from the chain to the given Span attributes.

        :param span: The Span to be configured
        :param output: The chain final return output
        :return: OpenTelemetry Span configured with agent-specific attributes
        """

    @abstractmethod
    def trace_llm(
        self,
        start_time: int,
        model: str,
        invocation_params: Any,
        response: LLMResponseDTO,
        **kwargs,
    ) -> Span:
        """
        Creates and configures a span for tracing LLM inference calls.

        :param start_time: Start time of the LLM call in nanoseconds since epoch
        :param model: The LLM model being used with the prefix of the provider (e.g., vertex_ai/claude-sonnet-4-6)
        :param invocation_params: Parameters passed to the LLM API call
        :param response: The LLM response containing text, tool calls, and metadata
        :param kwargs: Additional keyword arguments including messages, tools, and history
        :return: OpenTelemetry Span configured with LLM-specific attributes
        """

    @abstractmethod
    def trace_tool(self, start_time: int, output: Any, *args, **kwargs) -> Span:
        """
        Creates and configures a span for tracing tool operations.

        :param start_time: Start time of the LLM call in nanoseconds since epoch
        :param output: The tool response output
        :param args: arguments containing the tool input
        :param kwargs: Keyword arguments containing the tool input
        :return: OpenTelemetry Span configured with tool-specific attributes
        """
