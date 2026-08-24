# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from unittest.mock import MagicMock

from opentelemetry.trace import Span

from src.domains.dto import TerraformValidationDTO, ToolResultDTO
from src.domains.interfaces.tracer_interface import ITracer
from src.domains.services.tracer_service import (
    TracerService,
    trace_chain,
    trace_tool,
    trace_terraform,
)


class TestTracerServiceContextVar(unittest.TestCase):
    def test_set_and_get_current_tracer(self):
        mock_tracer = MagicMock(spec=ITracer)
        token = TracerService.set_current_tracer(mock_tracer)
        try:
            result = TracerService.get_current_tracer()
            self.assertIs(result, mock_tracer)
        finally:
            TracerService.reset_current_tracer(token)

    def test_get_without_set_raises_lookup_error(self):
        with self.assertRaises(LookupError):
            TracerService.get_current_tracer()

    def test_reset_restores_previous_state(self):
        mock_tracer = MagicMock(spec=ITracer)
        token = TracerService.set_current_tracer(mock_tracer)
        TracerService.reset_current_tracer(token)
        with self.assertRaises(LookupError):
            TracerService.get_current_tracer()


class TestTraceChainDecorator(unittest.IsolatedAsyncioTestCase):
    async def test_trace_chain_calls_tracer_methods(self):
        mock_tracer = MagicMock(spec=ITracer)
        mock_span = MagicMock(spec=Span)
        mock_tracer.trace_chain.return_value = mock_span
        mock_tracer.trace_chain_output.return_value = mock_span

        token = TracerService.set_current_tracer(mock_tracer)
        try:
            prompt_mock = MagicMock()
            prompt_mock.type.name = "TEST_CHAIN"

            @trace_chain
            async def dummy_chain(prompt=None, query=None):
                return "chain_output"

            result = await dummy_chain(prompt=prompt_mock, query="test query")
            self.assertEqual(result, "chain_output")
            mock_tracer.trace_chain.assert_called_once_with(
                prompt=prompt_mock, query="test query"
            )
            mock_tracer.trace_chain_output.assert_called_once_with(
                mock_span, "chain_output"
            )
            mock_span.set_status.assert_called_once()
            mock_span.end.assert_called_once()
        finally:
            TracerService.reset_current_tracer(token)


class TestTraceToolDecorator(unittest.IsolatedAsyncioTestCase):
    async def test_trace_tool_calls_tracer_method(self):
        mock_tracer = MagicMock(spec=ITracer)
        mock_span = MagicMock(spec=Span)
        mock_tracer.trace_tool.return_value = mock_span

        token = TracerService.set_current_tracer(mock_tracer)
        try:
            tool_output = ToolResultDTO(
                name="grep_search",
                tool_call_id="call_1",
                success=True,
                result="found it",
            )

            @trace_tool
            async def dummy_tool(tool_call=None):
                return tool_output

            result = await dummy_tool(tool_call="some_call")
            self.assertIs(result, tool_output)
            mock_tracer.trace_tool.assert_called_once()
            call_args = mock_tracer.trace_tool.call_args
            self.assertIsInstance(call_args[0][0], int)
            self.assertIs(call_args[0][1], tool_output)
            mock_span.set_status.assert_called_once()
            mock_span.end.assert_called_once()
        finally:
            TracerService.reset_current_tracer(token)


class TestTraceTerraformDecorator(unittest.IsolatedAsyncioTestCase):
    async def test_trace_terraform_calls_tracer_method(self):
        mock_tracer = MagicMock(spec=ITracer)
        mock_span = MagicMock(spec=Span)
        mock_tracer.trace_terraform.return_value = mock_span

        token = TracerService.set_current_tracer(mock_tracer)
        try:
            tf_dto = TerraformValidationDTO(
                validation=True,
                feedback="looks good",
                terraform_plan="plan output",
                terraform_targets=["azurerm_resource_group.rg"],
            )

            @trace_terraform
            async def dummy_terraform():
                return tf_dto

            result = await dummy_terraform()
            self.assertIs(result, tf_dto)
            mock_tracer.trace_terraform.assert_called_once()
            call_args = mock_tracer.trace_terraform.call_args
            self.assertIs(call_args[0][0], tf_dto)
            self.assertIn("start_time", call_args[1])
            self.assertIsInstance(call_args[1]["start_time"], int)
            mock_span.set_status.assert_called_once()
            mock_span.end.assert_called_once()
        finally:
            TracerService.reset_current_tracer(token)


class TestTraceLlmDecorator(unittest.IsolatedAsyncioTestCase):
    async def test_trace_llm_captures_params_and_traces(self):
        mock_tracer = MagicMock(spec=ITracer)
        mock_span = MagicMock(spec=Span)
        mock_tracer.trace_llm.return_value = mock_span

        token = TracerService.set_current_tracer(mock_tracer)
        try:
            from src.domains.services.tracer_service import trace_llm

            invocation_params = {"model": "test", "messages": []}

            @trace_llm
            async def fake_inference(self, msg=None, **kwargs):
                self._last_invocation_params = invocation_params
                return MagicMock(
                    text="ok",
                    tool_calls=[],
                    metadata=MagicMock(input_tokens=1, output_tokens=2),
                )

            adapter_mock = MagicMock()
            adapter_mock.model = "vertex_ai/claude-sonnet-4-6"

            await fake_inference(adapter_mock, msg="hello")

            mock_tracer.trace_llm.assert_called_once()
            call_kwargs = mock_tracer.trace_llm.call_args[1]
            self.assertEqual(call_kwargs["model"], "vertex_ai/claude-sonnet-4-6")
            self.assertEqual(call_kwargs["invocation_params"], invocation_params)
            mock_span.set_status.assert_called_once()
            mock_span.end.assert_called_once()
        finally:
            TracerService.reset_current_tracer(token)


if __name__ == "__main__":
    unittest.main()
