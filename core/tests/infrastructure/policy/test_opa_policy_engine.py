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
SEED_PROVIDERS = ("aws", "azurerm", "google", "kubernetes", "oci", "vsphere")
PROVIDER_SEEDS = {
    provider: (CORE / f"prompts/seed/{provider}/policies/compliance.rego").read_text(
        encoding="utf-8"
    )
    for provider in SEED_PROVIDERS
}


def _fixture(engine: str) -> dict:
    return json.loads((FIXTURES / engine / "data.json").read_text())["plan"]


def _change(address: str, actions: list[str]) -> dict:
    return {"address": address, "mode": "managed", "change": {"actions": actions}}


class _EngineTestCase(unittest.IsolatedAsyncioTestCase):
    def _policy(
        self,
        text: str,
        revision: str = "general/policies/compliance@1",
        providers: dict[str, str] | None = None,
    ) -> AsyncMock:
        """Langfuse holding the general policy ``text`` and the policy of
        each provider in ``providers``; any other prompt is missing."""
        policies = {"general": (text, revision)}
        for provider, rego in (providers or {}).items():
            policies[provider] = (rego, f"{provider}/policies/compliance@1")

        async def fetch(prompt_name: str, scope: str, type: str, tag: str):
            if scope not in policies:
                raise PromptFetchError(message="No version labelled", error_code=404)
            return policies[scope]

        fetch_mock = AsyncMock(side_effect=fetch)
        patcher = patch.object(remote_fetcher, "fetch_versioned", fetch_mock)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fetch_mock

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

                decision = await OpaPolicyEngine().evaluate(_fixture(engine), [])

                fetch.assert_awaited_once()
                assert fetch.await_args is not None
                self.assertEqual(fetch.await_args.kwargs["scope"], "general")
                self.assertEqual(fetch.await_args.kwargs["type"], "policies")
                [finding] = decision.violations
                self.assertEqual(finding.rule_id, "critical_deletion")
                self.assertEqual(finding.severity, "critical")
                self.assertEqual(finding.resource, "terraform_data.deleted")
                self.assertEqual(finding.source, "opa")
                self.assertEqual(
                    decision.checked_rules,
                    [
                        "command_execution",
                        "critical_deletion",
                        "customer_managed_key_removed",
                        "unprotected_credential_output",
                    ],
                )
                self.assertEqual(decision.revisions, ["general/policies/compliance@42"])

    async def test_provider_seeds_deny_their_real_plan_findings(self):
        # Findings in each real plan, and the prefix of the provider's rule ids.
        expected = {
            "aws": (6, "aws_"),
            "google": (5, "google_"),
            "kubernetes": (3, "k8s_"),
        }
        for provider, (findings, prefix) in expected.items():
            with self.subTest(provider=provider):
                _ = self._policy(SEED_POLICY, providers=PROVIDER_SEEDS)

                decision = await OpaPolicyEngine().evaluate(
                    _fixture(provider), [provider]
                )

                self.assertEqual(len(decision.violations), findings)
                self.assertTrue(
                    all(v.rule_id.startswith(prefix) for v in decision.violations)
                )
                self.assertEqual(
                    decision.revisions,
                    [
                        "general/policies/compliance@1",
                        f"{provider}/policies/compliance@1",
                    ],
                )

    async def test_seed_policies_tolerate_nulls_under_strict_builtin_errors(self):
        # `opa test` swallows builtin errors; the engine evaluates with
        # --strict-builtin-errors, where a builtin given a null raises and
        # the round would lock as policy_unavailable.
        def change(type_: str, after: dict | None, **extra) -> dict:
            body = {"actions": ["update"], "before": {}, "after": after}
            return {
                "type": type_,
                "address": f"{type_}.x",
                "mode": "managed",
                "change": body | extra,
            }

        plan = {
            "resource_changes": [
                change(
                    "azurerm_role_assignment",
                    {
                        "scope": "/subscriptions/0",
                        "role_definition_name": "Reader",
                        "role_definition_id": None,
                    },
                ),
                change(
                    "azurerm_network_security_rule",
                    {
                        "direction": None,
                        "access": None,
                        "protocol": None,
                        "source_address_prefix": "*",
                    },
                ),
                change("azurerm_virtual_machine_extension", {"type": None}),
                change(
                    "aws_security_group_rule",
                    {"type": "ingress", "protocol": None, "cidr_blocks": ["0.0.0.0/0"]},
                ),
                change("aws_iam_policy", {"policy": None}),
                change(
                    "google_project_iam_binding",
                    {"role": "roles/owner", "members": [None]},
                ),
                change(
                    "google_compute_firewall",
                    {
                        "direction": None,
                        "source_ranges": ["0.0.0.0/0"],
                        "allow": [{"protocol": None, "ports": None}],
                    },
                ),
                change(
                    "kubernetes_pod_v1",
                    {"spec": [{"volume": [{"host_path": [{"path": None}]}]}]},
                ),
                change(
                    "oci_identity_policy",
                    {"statements": [None, "Allow any-user to read buckets in tenancy"]},
                ),
                change(
                    "oci_core_security_list",
                    {
                        "ingress_security_rules": [
                            {"protocol": None, "source": "0.0.0.0/0"}
                        ]
                    },
                ),
                change(
                    "aws_ebs_volume",
                    None,
                    before={"kms_key_id": "k"},
                    after_unknown=True,
                ),
                {**change("terraform_data", {}), "module_address": None},
            ]
        }
        _ = self._policy(SEED_POLICY, providers=PROVIDER_SEEDS)

        decision = await OpaPolicyEngine().evaluate(plan, list(SEED_PROVIDERS))

        self.assertNotIn(
            "azurerm_subscription_owner", {v.rule_id for v in decision.violations}
        )
        self.assertIn(
            "oci_any_user_no_condition", {v.rule_id for v in decision.violations}
        )

    async def test_verify_passes_with_every_seed_policy(self):
        _ = self._policy(SEED_POLICY, providers=PROVIDER_SEEDS)
        await OpaPolicyEngine().verify(list(SEED_PROVIDERS))

    async def test_verify_passes_with_the_seed_policy(self):
        _ = self._policy(SEED_POLICY)
        await OpaPolicyEngine().verify([])


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
        self.assertIn("the policies define no package under `kumoss`", message)

    async def test_a_syntax_error_names_the_line(self):
        message = await self._error("package kumoss.compliance\ndeny contains x if {\n")
        self.assertIn("opa eval failed: general/policies/compliance:3:", message)

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
        self.assertIn("general/policies/compliance:3: eval_builtin_error", message)

    async def test_a_parse_error_keeps_its_message(self):
        message = await self._error("package kumoss.compliance\ndeny contains x if {\n")
        self.assertIn("unexpected eof token", message)


@unittest.skipUnless(shutil.which("opa"), "the opa binary is not on PATH")
class TestProviderPolicies(_EngineTestCase):
    GENERAL = """package kumoss.compliance
rules contains "general_rule"
"""
    AWS = """package kumoss.providers.aws
rules contains "aws_rule"
deny contains {"rule_id": "aws_rule", "message": "m", "resource": "aws_s3_bucket.a"}
"""

    async def test_a_declared_provider_policy_is_merged(self):
        _ = self._policy(self.GENERAL, providers={"aws": self.AWS})

        decision = await OpaPolicyEngine().evaluate({}, ["aws", "random"])

        self.assertEqual([v.rule_id for v in decision.violations], ["aws_rule"])
        self.assertEqual(decision.checked_rules, ["aws_rule", "general_rule"])
        # The general policy first; random has no policy and is skipped.
        self.assertEqual(
            decision.revisions,
            ["general/policies/compliance@1", "aws/policies/compliance@1"],
        )

    async def test_an_undeclared_provider_policy_is_not_fetched(self):
        fetch = self._policy(self.GENERAL, providers={"aws": self.AWS})

        decision = await OpaPolicyEngine().evaluate({}, ["azurerm"])

        self.assertEqual(decision.violations, [])
        scopes = [c.kwargs["scope"] for c in fetch.await_args_list]
        self.assertEqual(scopes, ["general", "azurerm"])

    async def test_a_provider_policy_in_the_wrong_package_is_an_error(self):
        _ = self._policy(
            self.GENERAL,
            providers={"aws": 'package kumoss.aws\nrules contains "x"\n'},
        )
        with self.assertRaises(PolicyEvaluationError) as ctx:
            _ = await OpaPolicyEngine().evaluate({}, ["aws"])
        self.assertIn(
            "aws/policies/compliance defines no `package kumoss.providers.aws`",
            ctx.exception.message,
        )

    async def test_a_provider_syntax_error_names_its_prompt(self):
        _ = self._policy(
            self.GENERAL, providers={"aws": "package kumoss.providers.aws\nx if {\n"}
        )
        with self.assertRaises(PolicyEvaluationError) as ctx:
            _ = await OpaPolicyEngine().evaluate({}, ["aws"])
        self.assertIn("aws/policies/compliance:3:", ctx.exception.message)

    async def test_a_provider_fetch_failure_other_than_404_is_an_error(self):
        async def fetch(prompt_name: str, scope: str, type: str, tag: str):
            if scope == "general":
                return (self.GENERAL, "general/policies/compliance@1")
            raise PromptFetchError(message="down", error_code=500)

        with patch.object(
            remote_fetcher, "fetch_versioned", AsyncMock(side_effect=fetch)
        ):
            with self.assertRaises(PolicyEvaluationError) as ctx:
                _ = await OpaPolicyEngine().evaluate({}, ["aws"])
        self.assertIn(
            "aws/policies/compliance could not be fetched", ctx.exception.message
        )

    async def test_verify_evaluates_the_provider_policies(self):
        broken = "package kumoss.providers.oci\nx if {\n"
        _ = self._policy(self.GENERAL, providers={"oci": broken})
        with self.assertRaises(PolicyEvaluationError):
            await OpaPolicyEngine().verify(["aws", "oci"])


class TestFailures(_EngineTestCase):
    async def test_a_fetch_failure_is_an_evaluation_error(self):
        fetch = AsyncMock(side_effect=PromptFetchError(message="down", error_code=502))
        with patch.object(remote_fetcher, "fetch_versioned", fetch):
            with self.assertRaises(PolicyEvaluationError) as ctx:
                await OpaPolicyEngine().verify([])
        self.assertIn("could not be fetched from Langfuse: down", ctx.exception.message)

    async def test_a_missing_binary_is_an_evaluation_error(self):
        _ = self._policy(SEED_POLICY)
        with patch.object(OpaPolicyEngine, "_BINARY", "kumoss-no-such-opa"):
            with self.assertRaises(PolicyEvaluationError) as ctx:
                await OpaPolicyEngine().verify([])
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
                await OpaPolicyEngine().verify([])

        proc.kill.assert_called_once()
        proc.wait.assert_awaited_once()
        self.assertIn("timed out", ctx.exception.message)
        self.assertEqual(ctx.exception.error_code, 504)


if __name__ == "__main__":
    unittest.main()
