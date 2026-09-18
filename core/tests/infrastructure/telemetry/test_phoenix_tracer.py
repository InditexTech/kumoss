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
    TerraformApplyDTO,
    TerraformDriftDTO,
    TerraformPlanDTO,
    ToolResultDTO,
    ToolCallDTO,
    PromptTemplateDTO,
)
from src.infrastructure.telemetry.phoenix.phoenix_tracer import PhoenixTracer
from src.shared.constants import TerraformProvider, PromptsLibrary, OperationType


def _make_tracer(**overrides) -> PhoenixTracer:
    defaults = dict(
        session_id=uuid4(),
        user_id="test-user",
        cloud=TerraformProvider.AZURE,
        repo_uri="https://example.com/repo.git",
        iac_path="/workspaces/test",
        operation=OperationType.GENERATE,
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
        tf_dto = TerraformPlanDTO(
            ok=True,
            feedback="",
            stdout="plan output",
            targets=["azurerm_resource_group.rg"],
            plan=None,
        )
        span = tracer.trace_terraform(tf_dto, operation="plan")
        self.assertIs(span, mock_span)

        set_calls = {c[0][0]: c[0][1] for c in mock_span.set_attribute.call_args_list}
        self.assertEqual(
            set_calls[SpanAttributes.OPENINFERENCE_SPAN_KIND],
            OpenInferenceSpanKindValues.EVALUATOR.value,
        )
        self.assertIn(SpanAttributes.OUTPUT_VALUE, set_calls)

    def test_every_terraform_result_traces_its_own_summary(self, mock_get_tracer):
        mock_otel_tracer = MagicMock()
        mock_get_tracer.return_value = mock_otel_tracer

        cases = [
            (
                "a successful plan traces the plan",
                "plan",
                TerraformPlanDTO(
                    ok=True,
                    feedback="",
                    stdout="plan output",
                    targets=[],
                    plan=None,
                ),
                True,
                "plan output",
            ),
            (
                "a failed plan traces the problem",
                "plan",
                TerraformPlanDTO(
                    ok=False,
                    feedback="Error: invalid resource",
                    stdout="partial plan",
                    targets=[],
                    plan=None,
                ),
                False,
                "Error: invalid resource",
            ),
            (
                "a drifted workspace traces the drift",
                "drift",
                TerraformDriftDTO(
                    in_sync=False,
                    drift="[drift]",
                    feedback="",
                    stdout="plan output",
                    plan=None,
                ),
                False,
                "[drift]",
            ),
            (
                "an unreadable drift traces the problem",
                "drift",
                TerraformDriftDTO(
                    in_sync=False,
                    drift="",
                    feedback="Error: stale plan file",
                    stdout="plan output",
                    plan=None,
                ),
                False,
                "Error: stale plan file",
            ),
            (
                "a synchronized workspace traces the plan",
                "drift",
                TerraformDriftDTO(
                    in_sync=True,
                    drift="",
                    feedback="",
                    stdout="plan output",
                    plan=None,
                ),
                True,
                "plan output",
            ),
            (
                "an apply traces its output",
                "apply",
                TerraformApplyDTO(ok=True, stdout="apply output", feedback=""),
                True,
                "apply output",
            ),
            (
                "a failed apply traces the problem",
                "apply",
                TerraformApplyDTO(
                    ok=False, stdout="partial apply", feedback="Error: state lock"
                ),
                False,
                "Error: state lock",
            ),
        ]

        for label, operation, dto, expected_ok, expected_output in cases:
            with self.subTest(label):
                mock_span = MagicMock()
                mock_otel_tracer.start_span.return_value = mock_span

                _ = _make_tracer().trace_terraform(dto, operation=operation)

                # The verb names the span, so plan, drift and apply are
                # separable in Phoenix; the outcome boolean stays in it.
                self.assertEqual(
                    mock_otel_tracer.start_span.call_args.kwargs["name"],
                    f"Terraform {operation} - {expected_ok}",
                )
                set_calls = {
                    c[0][0]: c[0][1] for c in mock_span.set_attribute.call_args_list
                }
                self.assertEqual(
                    set_calls[SpanAttributes.OUTPUT_VALUE], expected_output
                )


if __name__ == "__main__":
    unittest.main()
