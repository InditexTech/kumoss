# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from typing import Any

from abc import ABC, abstractmethod
from opentelemetry.trace import Span

from src.domains.dto import TerraformValidationDTO


class ITracer(ABC):
    @abstractmethod
    def trace_terraform(
        self, terraformDTO: TerraformValidationDTO, **kwargs: Any
    ) -> Span:
        """
        Creates and configures a span for tracing Terraform operations.

        :param terraformDTO: TerraformValidationDTO with all the goodies
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
    def trace_tool(self, start_time: int, output: Any, *args, **kwargs) -> Span:
        """
        Creates and configures a span for tracing tool operations.

        :param start_time: Start time of the LLM call in nanoseconds since epoch
        :param output: The tool response output
        :param args: arguments containing the tool input
        :param kwargs: Keyword arguments containing the tool input
        :return: OpenTelemetry Span configured with tool-specific attributes
        """
