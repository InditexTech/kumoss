# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import json
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

from src.domains.dto import (
    LLMMetadata,
    LLMResponseDTO,
    PromptTemplateDTO,
    TerraformApplyDTO,
    TerraformDriftDTO,
    TerraformPlanDTO,
    ToolCallDTO,
    ToolDefinitionDTO,
    ToolResultDTO,
)
from src.domains.entities.history import History
from src.domains.value_objects import PlanRef
from src.infrastructure.telemetry.langfuse_tracer import (
    Attr,
    LangfuseTracer,
    _serialize,
)
from src.shared.constants import OperationType, PromptsLibrary, ToolContext

PLAN_TEXT = "the full terraform plan text"
SESSION_ID = uuid4()


def _plan_ref() -> PlanRef:
    return PlanRef(
        workspace=Path("/workspaces/demo"),
        plan_file="session.plan",
        targets=("module.kvt_001",),
        commit="a" * 64,
        stdout=PLAN_TEXT,
    )


def _make_tracer(**overrides: Any) -> LangfuseTracer:
    defaults: dict[str, Any] = dict(
        session_id=SESSION_ID,
        user_id="test-user",
        providers=("azurerm",),
        repo_uri="https://example.com/repo.git",
        root_module_path="/workspaces/test",
        operation=OperationType.GENERATE,
        branch_name="feat/test",
    )
    defaults.update(overrides)
    return LangfuseTracer(**defaults)


def _attributes(span: MagicMock) -> dict[str, Any]:
    return {c[0][0]: c[0][1] for c in span.set_attribute.call_args_list}


class _TracerTest(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch("src.infrastructure.telemetry.langfuse_tracer.get_tracer")
        self.otel = MagicMock()
        patcher.start().return_value = self.otel
        self.addCleanup(patcher.stop)

    def _spans(self, count: int) -> list[MagicMock]:
        spans = [MagicMock() for _ in range(count)]
        self.otel.start_span.side_effect = spans
        return spans

    def _chain(self, tracer: LangfuseTracer, query: Any = "test") -> MagicMock:
        prompt = PromptTemplateDTO(type=PromptsLibrary.IAC_GENERATOR, prompt="generate")
        return tracer.trace_chain(prompt=prompt, query=query)


class TestTraceAttributes(_TracerTest):
    def test_every_span_carries_the_session_user_environment_and_tags(self):
        chain, tool = self._spans(2)
        tracer = _make_tracer(providers=("azurerm", "random"))
        self._chain(tracer)
        tracer.trace_tool(
            0, ToolResultDTO(name="t", tool_call_id="c", success=True, result="ok")
        )

        for span in (chain, tool):
            attributes = _attributes(span)
            self.assertEqual(attributes[Attr.SESSION_ID], str(SESSION_ID))
            self.assertEqual(attributes[Attr.USER_ID], "test-user")
            self.assertEqual(attributes[Attr.ENVIRONMENT], "development")
            # One project for every operation: the operation is a tag.
            self.assertEqual(
                attributes[Attr.TRACE_TAGS], ("generate", "azurerm", "random")
            )
            self.assertEqual(
                attributes[f"{Attr.TRACE_METADATA}.repo_uri"],
                "https://example.com/repo.git",
            )
            self.assertEqual(
                attributes[f"{Attr.TRACE_METADATA}.providers"], "azurerm,random"
            )


class TestChain(_TracerTest):
    def test_a_chain_is_an_agent_observation(self):
        (span,) = self._spans(1)

        returned = self._chain(_make_tracer(), query="create a storage account")

        self.assertIs(returned, span)
        self.assertIn("Chain", self.otel.start_span.call_args.kwargs["name"])
        attributes = _attributes(span)
        self.assertEqual(attributes[Attr.TYPE], "agent")
        self.assertEqual(attributes[Attr.INPUT], "create a storage account")
        self.assertEqual(attributes[f"{Attr.METADATA}.chain_type"], "IAC_GENERATOR")

    def test_a_tool_result_output_is_traced_as_its_summary(self):
        (span,) = self._spans(1)
        tracer = _make_tracer()
        self._chain(tracer)

        tracer.trace_chain_output(
            span,
            ToolResultDTO(
                name="finish",
                tool_call_id="c",
                success=True,
                result={"summary": "all done", "files": ["main.tf"]},
            ),
        )

        self.assertEqual(_attributes(span)[Attr.OUTPUT], "all done")


class TestTool(_TracerTest):
    def test_a_tool_call_is_a_tool_observation_under_the_chain(self):
        chain, tool_span = self._spans(2)
        tracer = _make_tracer()
        self._chain(tracer)

        call = ToolCallDTO(id="call_1", name="grep_search", parameters={"q": "x"})
        result = ToolResultDTO(
            name="grep_search", tool_call_id="call_1", success=True, result="found"
        )
        returned = tracer.trace_tool(1_000, result, tool_call=call)

        self.assertIs(returned, tool_span)
        self.assertIsNotNone(self.otel.start_span.call_args.kwargs["context"])
        attributes = _attributes(tool_span)
        self.assertEqual(attributes[Attr.TYPE], "tool")
        self.assertEqual(json.loads(attributes[Attr.INPUT]), {"q": "x"})
        self.assertEqual(attributes[f"{Attr.METADATA}.tool_name"], "grep_search")
        self.assertEqual(attributes[f"{Attr.METADATA}.tool_call_id"], "call_1")
        self.assertNotIn(Attr.LEVEL, attributes)

    def test_a_failed_tool_call_is_an_error_with_its_message(self):
        _, tool_span = self._spans(2)
        tracer = _make_tracer()
        self._chain(tracer)

        tracer.trace_tool(
            0,
            ToolResultDTO(
                name="read_file",
                tool_call_id="c",
                success=False,
                result=None,
                error_message="no such file",
            ),
            tool_call=ToolCallDTO(id="c", name="read_file", parameters={}),
        )

        attributes = _attributes(tool_span)
        self.assertEqual(attributes[Attr.LEVEL], "ERROR")
        self.assertEqual(attributes[Attr.STATUS_MESSAGE], "no such file")


class TestGeneration(_TracerTest):
    def _trace(self, response: LLMResponseDTO, **kwargs: Any) -> dict[str, Any]:
        _, span = self._spans(2)
        tracer = _make_tracer()
        self._chain(tracer)
        tracer.trace_llm(
            start_time=0,
            model="anthropic/claude-sonnet-4-6",
            invocation_params={"temperature": 0.2, "thinking": {"type": "disabled"}},
            response=response,
            **kwargs,
        )
        return _attributes(span)

    def _response(self, text: str = "", tool_calls: list[ToolCallDTO] | None = None):
        return LLMResponseDTO(
            text=text,
            metadata=LLMMetadata(
                input_tokens=100,
                output_tokens=20,
                finish_reason="tool_use" if tool_calls else "end_turn",
                model="claude-sonnet-4-6",
            ),
            tool_calls=tool_calls or [],
        )

    def test_a_generation_carries_model_parameters_and_usage(self):
        attributes = self._trace(self._response("hello"), msg="hi")

        self.assertEqual(attributes[Attr.TYPE], "generation")
        # Without LiteLLM's provider prefix, as Langfuse's model prices name it.
        self.assertEqual(attributes[Attr.MODEL], "claude-sonnet-4-6")
        self.assertEqual(attributes[f"{Attr.METADATA}.llm_provider"], "anthropic")
        self.assertEqual(
            json.loads(attributes[Attr.MODEL_PARAMETERS]),
            {"temperature": 0.2, "thinking": '{"type": "disabled"}'},
        )
        self.assertEqual(
            json.loads(attributes[Attr.USAGE]),
            {"input": 100, "output": 20, "total": 120},
        )

    def test_the_conversation_is_traced_as_chat_messages(self):
        history = History()
        history.append_turn(
            user_msg="create a bucket",
            assistant_msg=[
                ToolCallDTO(id="c1", name="read_file", parameters={"p": "a"})
            ],
        )
        history.append_turn(
            user_msg=[
                ToolResultDTO(
                    name="read_file", tool_call_id="c1", success=True, result="x"
                )
            ],
            assistant_msg="done reading",
        )

        attributes = self._trace(
            self._response("ok"),
            msg=[
                ToolResultDTO(
                    name="t",
                    tool_call_id="c2",
                    success=False,
                    result=None,
                    error_message="boom",
                )
            ],
            history=history,
            system_prompt="you are kumoss",
            notice="2 turns left",
        )

        self.assertEqual(
            json.loads(attributes[Attr.INPUT]),
            [
                {"role": "system", "content": "you are kumoss"},
                {"role": "user", "content": "create a bucket"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"p": "a"}',
                            },
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "c1", "content": "x"},
                {"role": "assistant", "content": "done reading"},
                {"role": "tool", "tool_call_id": "c2", "content": "boom"},
                {"role": "user", "content": "2 turns left"},
            ],
        )

    def test_the_answer_is_one_assistant_message_with_its_tool_calls(self):
        call = ToolCallDTO(id="c9", name="write_file", parameters={"path": "main.tf"})

        attributes = self._trace(self._response("writing", [call]), msg="go")

        self.assertEqual(
            json.loads(attributes[Attr.OUTPUT]),
            {
                "role": "assistant",
                "content": "writing",
                "tool_calls": [
                    {
                        "id": "c9",
                        "type": "function",
                        "function": {
                            "name": "write_file",
                            "arguments": '{"path": "main.tf"}',
                        },
                    }
                ],
            },
        )

    def test_the_offered_tools_are_traced_in_the_function_format(self):
        tool = ToolDefinitionDTO(
            name="read_file",
            description="Reads a file",
            parameters={"type": "object"},
            context=next(iter(ToolContext)),
            single_use=False,
            mutates_workspace=False,
        )

        attributes = self._trace(self._response("x"), msg="go", tools=[tool])

        self.assertEqual(
            json.loads(attributes[f"{Attr.METADATA}.tools"]),
            [
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Reads a file",
                        "parameters": {"type": "object"},
                    },
                }
            ],
        )


class TestTerraform(_TracerTest):
    def test_a_terraform_run_is_an_evaluator_observation(self):
        (span,) = self._spans(1)
        dto = TerraformPlanDTO(
            ok=True, feedback="", stdout="plan output", targets=[], plan=None
        )

        self.assertIs(_make_tracer().trace_terraform(dto, operation="plan"), span)

        attributes = _attributes(span)
        self.assertEqual(attributes[Attr.TYPE], "evaluator")
        self.assertEqual(attributes[Attr.OUTPUT], "plan output")

    def test_the_traced_plan_reference_is_an_identity_not_a_plan(self):
        (span,) = self._spans(1)
        ref = _plan_ref()
        drift = TerraformDriftDTO(
            in_sync=True, drift="", feedback="", stdout=PLAN_TEXT, plan=ref
        )

        _ = _make_tracer().trace_terraform(drift, operation="drift", plan=ref)

        traced_input = _attributes(span)[Attr.INPUT]
        # A drift read receives nothing but the ref, so the input says
        # which plan was read; the plan text is the span's output, not
        # something to duplicate into its input.
        self.assertIn("session.plan", traced_input)
        self.assertIn("module.kvt_001", traced_input)
        self.assertNotIn(PLAN_TEXT, traced_input)

    def test_every_terraform_result_traces_its_own_summary(self):
        cases = [
            (
                "a successful plan traces the plan",
                "plan",
                TerraformPlanDTO(
                    ok=True, feedback="", stdout="plan output", targets=[], plan=None
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
                    in_sync=True, drift="", feedback="", stdout="plan output", plan=None
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
                (span,) = self._spans(1)

                _ = _make_tracer().trace_terraform(dto, operation=operation)

                # The verb names the span, so plan, drift and apply are
                # separable in Langfuse; the outcome boolean stays in it.
                self.assertEqual(
                    self.otel.start_span.call_args.kwargs["name"],
                    f"Terraform {operation} - {expected_ok}",
                )
                self.assertEqual(_attributes(span)[Attr.OUTPUT], expected_output)


class TestSerialize(unittest.TestCase):
    def test_a_field_kept_out_of_a_repr_stays_out_of_a_span(self):
        value = _serialize(_plan_ref())

        # Whatever a dataclass hides from its own repr is hidden from the
        # trace too: serializing a ref must not be a way around the
        # decision its type already made.
        self.assertIn("session.plan", json.loads(value)["plan_file"])
        self.assertNotIn(PLAN_TEXT, value)

    def test_a_string_is_traced_as_it_is(self):
        self.assertEqual(_serialize("plain text"), "plain text")


if __name__ == "__main__":
    unittest.main()
