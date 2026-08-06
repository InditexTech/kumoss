# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from unittest.mock import patch, MagicMock
from uuid import uuid4

from openinference.semconv.trace import (
    OpenInferenceSpanKindValues,
    SpanAttributes,
)

from src.domains.dto import (
    TerraformValidationDTO,
    ToolResultDTO,
    ToolCallDTO,
    PromptTemplateDTO,
)
from src.infrastructure.telemetry.phoenix.phoenix_tracer import PhoenixTracer
from src.shared.constants import TerraformProvider, PromptsLibrary


def _make_tracer(**overrides) -> PhoenixTracer:
    defaults = dict(
        session_id=uuid4(),
        user_id="test-user",
        cloud=TerraformProvider.AZURE,
        iac_path="/workspaces/test",
        branch_name="feat/test",
    )
    defaults.update(overrides)
    return PhoenixTracer(**defaults)


@patch("src.infrastructure.telemetry.phoenix.phoenix_tracer.get_tracer")
class TestPhoenixTracerChain(unittest.TestCase):
    def test_trace_chain_creates_span_with_agent_kind(self, mock_get_tracer):
        mock_otel_tracer = MagicMock()
        mock_span = MagicMock()
        mock_otel_tracer.start_span.return_value = mock_span
        mock_get_tracer.return_value = mock_otel_tracer

        tracer = _make_tracer()
        prompt = PromptTemplateDTO(type=PromptsLibrary.IAC_GENERATOR, prompt="generate")
        span = tracer.trace_chain(prompt=prompt, query="create a storage account")

        mock_otel_tracer.start_span.assert_called_once()
        call_args, call_kwargs = mock_otel_tracer.start_span.call_args
        call_name = call_kwargs.get("name") or call_args[0]
        self.assertIn("Chain", call_name)
        self.assertIs(span, mock_span)

        set_calls = {c[0][0]: c[0][1] for c in mock_span.set_attribute.call_args_list}
        self.assertEqual(
            set_calls[SpanAttributes.OPENINFERENCE_SPAN_KIND],
            OpenInferenceSpanKindValues.AGENT.value,
        )
        self.assertIn(SpanAttributes.SESSION_ID, set_calls)
        self.assertIn(SpanAttributes.USER_ID, set_calls)
        self.assertIn(SpanAttributes.INPUT_VALUE, set_calls)

    def test_trace_chain_output_adds_output_attribute(self, mock_get_tracer):
        mock_otel_tracer = MagicMock()
        mock_span = MagicMock()
        mock_otel_tracer.start_span.return_value = mock_span
        mock_get_tracer.return_value = mock_otel_tracer

        tracer = _make_tracer()
        prompt = PromptTemplateDTO(type=PromptsLibrary.IAC_GENERATOR, prompt="generate")
        span = tracer.trace_chain(prompt=prompt, query="test")
        tracer.trace_chain_output(span, "the output text")

        output_keys = [c[0][0] for c in mock_span.set_attribute.call_args_list]
        self.assertIn(SpanAttributes.OUTPUT_VALUE, output_keys)


@patch("src.infrastructure.telemetry.phoenix.phoenix_tracer.get_tracer")
class TestPhoenixTracerTool(unittest.TestCase):
    def test_trace_tool_creates_span_with_tool_kind(self, mock_get_tracer):
        mock_otel_tracer = MagicMock()
        mock_chain_span = MagicMock()
        mock_tool_span = MagicMock()
        mock_otel_tracer.start_span.side_effect = [mock_chain_span, mock_tool_span]
        mock_get_tracer.return_value = mock_otel_tracer

        tracer = _make_tracer()
        prompt = PromptTemplateDTO(
            type=PromptsLibrary.TARGET_GENERATOR, prompt="generate targets"
        )
        tracer.trace_chain(prompt=prompt, query="test")

        tool_call = ToolCallDTO(id="call_1", name="grep_search", parameters={"q": "x"})
        tool_output = ToolResultDTO(
            name="grep_search",
            tool_call_id="call_1",
            success=True,
            result="found",
        )

        start_ns = 1_000_000_000
        span = tracer.trace_tool(start_ns, tool_output, tool_call=tool_call)
        self.assertIs(span, mock_tool_span)

        set_calls = {
            c[0][0]: c[0][1] for c in mock_tool_span.set_attribute.call_args_list
        }
        self.assertEqual(
            set_calls[SpanAttributes.OPENINFERENCE_SPAN_KIND],
            OpenInferenceSpanKindValues.TOOL.value,
        )


@patch("src.infrastructure.telemetry.phoenix.phoenix_tracer.get_tracer")
class TestPhoenixTracerTerraform(unittest.TestCase):
    def test_trace_terraform_creates_span_with_evaluator_kind(self, mock_get_tracer):
        mock_otel_tracer = MagicMock()
        mock_span = MagicMock()
        mock_otel_tracer.start_span.return_value = mock_span
        mock_get_tracer.return_value = mock_otel_tracer

        tracer = _make_tracer()
        tf_dto = TerraformValidationDTO(
            validation=True,
            feedback="all good",
            terraform_plan="plan output",
            terraform_targets=["azurerm_resource_group.rg"],
        )
        span = tracer.trace_terraform(tf_dto)
        self.assertIs(span, mock_span)

        set_calls = {c[0][0]: c[0][1] for c in mock_span.set_attribute.call_args_list}
        self.assertEqual(
            set_calls[SpanAttributes.OPENINFERENCE_SPAN_KIND],
            OpenInferenceSpanKindValues.EVALUATOR.value,
        )
        self.assertIn(SpanAttributes.OUTPUT_VALUE, set_calls)


if __name__ == "__main__":
    unittest.main()
