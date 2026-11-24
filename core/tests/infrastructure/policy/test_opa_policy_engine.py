# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic
"""The OPA adapter against the real ``opa`` binary.

Skipped when ``opa`` is not on PATH (the core image ships it). The plans
are the real ``show -json`` fixtures the Rego tests use too.
"""

import asyncio
import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.domains.exceptions import PolicyEvaluationError
from src.infrastructure.exceptions import PromptFetchError
from src.infrastructure.policy import OpaPolicyEngine
from src.infrastructure.templates._fetcher import remote_fetcher

CORE = Path(__file__).resolve().parents[3]
SEED_POLICY = (CORE / "prompts/seed/general/policies/compliance.rego").read_text(
    encoding="utf-8"
)
FIXTURES = CORE / "tests/policies/fixtures"


def _fixture(engine: str) -> dict:
    return json.loads((FIXTURES / engine / "data.json").read_text())["plan"]


def _change(address: str, actions: list[str]) -> dict:
    return {"address": address, "mode": "managed", "change": {"actions": actions}}


class _EngineTestCase(unittest.IsolatedAsyncioTestCase):
    def _policy(
        self, text: str, revision: str = "general/policies/compliance@1"
    ) -> AsyncMock:
        fetch = AsyncMock(return_value=(text, revision))
        patcher = patch.object(remote_fetcher, "fetch_versioned", fetch)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fetch

    async def _evaluate(self, policy: str, changes: list[dict] | None = None):
        _ = self._policy(policy)
        plan = {"resource_changes": changes or []}
        return await OpaPolicyEngine().evaluate(plan, ["azurerm"])

    async def _error(self, policy: str, changes: list[dict] | None = None) -> str:
        with self.assertRaises(PolicyEvaluationError) as ctx:
            _ = await self._evaluate(policy, changes)
        return ctx.exception.message


@unittest.skipUnless(shutil.which("opa"), "the opa binary is not on PATH")
class TestSeedPolicy(_EngineTestCase):
    async def test_fixtures_deny_only_the_standalone_delete(self):
        for engine in ("terraform", "opentofu"):
            with self.subTest(engine=engine):
                fetch = self._policy(SEED_POLICY, "general/policies/compliance@42")

                decision = await OpaPolicyEngine().evaluate(_fixture(engine), ["x"])

                fetch.assert_awaited_once()
                assert fetch.await_args is not None
                self.assertEqual(fetch.await_args.kwargs["type"], "policies")
                [finding] = decision.violations
                self.assertEqual(finding.rule_id, "critical_deletion")
                self.assertEqual(finding.severity, "critical")
                self.assertEqual(finding.resource, "terraform_data.deleted")
                self.assertEqual(finding.source, "opa")
                self.assertEqual(decision.checked_rules, ["critical_deletion"])
                self.assertEqual(decision.revision, "general/policies/compliance@42")

    async def test_verify_passes_with_the_seed_policy(self):
        _ = self._policy(SEED_POLICY)
        await OpaPolicyEngine().verify()


@unittest.skipUnless(shutil.which("opa"), "the opa binary is not on PATH")
class TestDecisionContract(_EngineTestCase):
    async def test_the_input_carries_the_schema_and_providers(self):
        decision = await self._evaluate(
            """package kumoss.compliance
warn contains {"rule_id": "echo", "message": json.marshal(input.kumoss)}
"""
        )
        self.assertEqual(
            json.loads(decision.violations[0].message),
            {"schema": "kumoss.compliance.input/v1", "providers": ["azurerm"]},
        )

    async def test_findings_map_to_severities_and_sort(self):
        decision = await self._evaluate(
            """package kumoss.compliance
deny contains {"rule_id": "b_rule", "message": "m", "extra": "ignored"}
deny contains {"rule_id": "a_rule", "message": "m", "severity": "critical"}
warn contains {"rule_id": "c_rule", "message": "m", "resource": "x.y"}
rules contains "d_rule"
"""
        )
        self.assertEqual(
            [(v.rule_id, v.severity) for v in decision.violations],
            [("a_rule", "critical"), ("b_rule", "error"), ("c_rule", "warning")],
        )
        self.assertEqual(decision.violations[2].resource, "x.y")
        self.assertEqual(
            decision.checked_rules, ["a_rule", "b_rule", "c_rule", "d_rule"]
        )

    async def test_an_empty_package_is_a_clean_decision(self):
        decision = await self._evaluate("package kumoss.compliance\n")
        self.assertEqual((decision.violations, decision.checked_rules), ([], []))

    async def test_a_missing_package_is_an_error(self):
        message = await self._error("package something.else\nx := 1\n")
        self.assertIn("defines no `package kumoss.compliance`", message)

    async def test_a_syntax_error_names_the_line(self):
        message = await self._error("package kumoss.compliance\ndeny contains x if {\n")
        self.assertIn("opa eval failed: compliance.rego:", message)

    async def test_a_builtin_error_is_an_error_not_an_empty_deny(self):
        message = await self._error(
            """package kumoss.compliance
deny contains {"rule_id": "r", "message": "m"} if to_number("not a number") > 1
"""
        )
        self.assertIn("opa eval failed", message)

    async def test_a_deny_severity_outside_the_contract_is_an_error(self):
        message = await self._error(
            """package kumoss.compliance
deny contains {"rule_id": "r", "message": "m", "severity": "warning"}
"""
        )
        self.assertIn("severity 'warning'", message)

    async def test_a_finding_without_a_message_is_an_error(self):
        message = await self._error(
            'package kumoss.compliance\ndeny contains {"rule_id": "r"}\n'
        )
        self.assertIn("has no `message`", message)

    async def test_a_non_set_output_is_an_error(self):
        message = await self._error('package kumoss.compliance\ndeny := "nope"\n')
        self.assertIn("`deny` must be a set", message)


@unittest.skipUnless(shutil.which("opa"), "the opa binary is not on PATH")
class TestErrorsQuoteNoPlanValue(_EngineTestCase):
    """The plan carries secrets unmasked, and an evaluation error reaches
    the logs and the stored report: no error may echo a plan value."""

    SECRET = "hunter2-not-for-logs"

    def _secret_changes(self) -> list[dict]:
        change = _change("aws_db_instance.main", ["update"])
        change["change"]["after"] = {"password": self.SECRET}
        return [change]

    async def test_a_finding_without_rule_id_lists_only_its_keys(self):
        message = await self._error(
            """package kumoss.compliance
deny contains c if some c in input.plan.resource_changes
""",
            self._secret_changes(),
        )
        self.assertNotIn(self.SECRET, message)
        self.assertIn("keys: address, change, mode", message)

    async def test_a_non_object_finding_gives_only_its_type(self):
        message = await self._error(
            """package kumoss.compliance
deny contains p if p := input.plan.resource_changes[_].change.after.password
""",
            self._secret_changes(),
        )
        self.assertNotIn(self.SECRET, message)
        self.assertIn("got a str", message)

    async def test_a_runtime_error_gives_only_its_code(self):
        # OPA's builtin errors quote their operands.
        message = await self._error(
            """package kumoss.compliance
deny contains {"rule_id": "r", "message": "m"} if {
	to_number(input.plan.resource_changes[_].change.after.password) > 1
}
""",
            self._secret_changes(),
        )
        self.assertNotIn(self.SECRET, message)
        self.assertIn("compliance.rego:3: eval_builtin_error", message)

    async def test_a_parse_error_keeps_its_message(self):
        message = await self._error("package kumoss.compliance\ndeny contains x if {\n")
        self.assertIn("unexpected eof token", message)


class TestFailures(_EngineTestCase):
    async def test_a_fetch_failure_is_an_evaluation_error(self):
        fetch = AsyncMock(side_effect=PromptFetchError(message="down", error_code=502))
        with patch.object(remote_fetcher, "fetch_versioned", fetch):
            with self.assertRaises(PolicyEvaluationError) as ctx:
                await OpaPolicyEngine().verify()
        self.assertIn("could not be fetched from Langfuse: down", ctx.exception.message)

    async def test_a_missing_binary_is_an_evaluation_error(self):
        _ = self._policy(SEED_POLICY)
        with patch.object(OpaPolicyEngine, "_BINARY", "kumoss-no-such-opa"):
            with self.assertRaises(PolicyEvaluationError) as ctx:
                await OpaPolicyEngine().verify()
        self.assertIn("could not be run", ctx.exception.message)

    async def test_a_hung_evaluation_is_killed(self):
        _ = self._policy(SEED_POLICY)

        async def hang(_stdin: bytes):
            await asyncio.sleep(60)

        proc = MagicMock()
        proc.communicate = hang
        proc.wait = AsyncMock(return_value=-9)
        spawn = AsyncMock(return_value=proc)
        with (
            patch.object(OpaPolicyEngine, "_TIMEOUT_SECONDS", 0.01),
            patch("asyncio.create_subprocess_exec", spawn),
        ):
            with self.assertRaises(PolicyEvaluationError) as ctx:
                await OpaPolicyEngine().verify()

        proc.kill.assert_called_once()
        proc.wait.assert_awaited_once()
        self.assertIn("timed out", ctx.exception.message)
        self.assertEqual(ctx.exception.error_code, 504)


if __name__ == "__main__":
    unittest.main()
