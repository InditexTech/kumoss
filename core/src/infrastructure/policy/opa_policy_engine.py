# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Evaluates the compliance policy with the ``opa`` binary.

The policy is the ``general/policies/compliance`` Langfuse prompt: a single
Rego v1 module, ``package kumoss.compliance``, fetched on every evaluation
so moving the environment label in Langfuse applies to the next session. Each evaluation
is one ``opa eval`` process reading the input on stdin; nothing stays
running between sessions.

Decision contract (all optional, a missing one counts as empty):

- ``deny``: blocking findings, ``{"rule_id", "message", "resource"?,
  "severity"?}`` with severity ``error`` (the default) or ``critical``.
- ``warn``: non-blocking findings, the same shape without a severity;
  reported as ``warning``.
- ``rules``: every rule id the policy evaluates, passed or not.

Keys outside the contract are ignored. Anything else that is off — no
such package, a wrong type, a deny severity outside the two — is a
PolicyEvaluationError, never an empty decision.
"""

import asyncio
import json
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, final, override

from src.domains.dto import ComplianceViolation, PolicyDecision
from src.domains.exceptions import PolicyEvaluationError
from src.domains.interfaces import IPolicyEngine
from src.infrastructure.exceptions import PromptFetchError
from src.infrastructure.templates._fetcher import remote_fetcher
from src.shared.config import system_config
from src.shared.logger import logging


@final
class OpaPolicyEngine(IPolicyEngine):
    _BINARY: str = "opa"
    _QUERY: str = "data.kumoss.compliance"
    _INPUT_SCHEMA: str = "kumoss.compliance.input/v1"
    # The Langfuse prompt `general/policies/compliance`.
    _POLICY_SCOPE: str = "general"
    _POLICY_NAME: str = "compliance"
    # The file name OPA reports policy errors against.
    _POLICY_FILE: str = "compliance.rego"
    _TIMEOUT_SECONDS: float = 30.0

    @override
    async def evaluate(
        self, plan_json: dict[str, Any], providers: Sequence[str]
    ) -> PolicyDecision:
        policy, revision = await self.__fetch_policy()
        document = {
            "plan": plan_json,
            "kumoss": {"schema": self._INPUT_SCHEMA, "providers": list(providers)},
        }
        value = await self.__eval(policy, json.dumps(document).encode())
        decision = self.__decision(value, revision)
        logging.info(
            f"Compliance policy {revision}: "
            + f"{sum(v.blocking for v in decision.violations)} denied, "
            + f"{sum(not v.blocking for v in decision.violations)} warned"
        )
        return decision

    @override
    async def verify(self) -> None:
        _ = await self.evaluate({"resource_changes": []}, [])

    async def __fetch_policy(self) -> tuple[str, str]:
        try:
            return await remote_fetcher.fetch_versioned(
                prompt_name=self._POLICY_NAME,
                scope=self._POLICY_SCOPE,
                type="policies",
                tag=system_config.environment,
            )
        except PromptFetchError as e:
            raise PolicyEvaluationError(
                message=f"the policy could not be fetched from Langfuse: {e.message}",
                error_code=502,
            ) from e

    async def __eval(self, policy: str, document: bytes) -> dict[str, Any]:
        """The value of the decision query; raises when there is none."""
        with tempfile.TemporaryDirectory(prefix="kumoss-policy-") as tmp:
            policy_path = Path(tmp) / self._POLICY_FILE
            _ = policy_path.write_text(policy, encoding="utf-8")
            exit_code, stdout, stderr = await self.__run(
                "eval",
                "--stdin-input",
                "--strict-builtin-errors",
                "--format",
                "json",
                "--data",
                policy_path.as_posix(),
                self._QUERY,
                stdin=document,
            )

        try:
            output = json.loads(stdout) if stdout.strip() else {}
        except json.JSONDecodeError:
            output = None
        if exit_code != 0:
            raise PolicyEvaluationError(
                message=f"opa eval failed: {self.__errors(output, stderr)}",
                error_code=502,
            )
        if not isinstance(output, dict):
            raise PolicyEvaluationError(
                message=f"opa eval printed no JSON result: {stderr.strip()}",
                error_code=502,
            )
        try:
            value = output["result"][0]["expressions"][0]["value"]
        except (KeyError, IndexError, TypeError) as e:
            raise PolicyEvaluationError(
                message="the policy defines no `package kumoss.compliance`",
                error_code=502,
            ) from e
        if not isinstance(value, dict):
            raise PolicyEvaluationError(
                message=f"{self._QUERY} is not an object",
                error_code=502,
            )
        return value

    async def __run(self, *args: str, stdin: bytes) -> tuple[int, str, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._BINARY,
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            raise PolicyEvaluationError(
                message=f"the `{self._BINARY}` binary could not be run: {e}",
                error_code=500,
            ) from e
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(stdin), timeout=self._TIMEOUT_SECONDS
            )
        except TimeoutError as e:
            proc.kill()
            _ = await proc.wait()
            raise PolicyEvaluationError(
                message=f"opa eval timed out after {self._TIMEOUT_SECONDS:g}s",
                error_code=504,
            ) from e
        return (
            proc.returncode or 0,
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
        )

    @classmethod
    def __errors(cls, output: Any, stderr: str) -> str:
        """OPA's errors, one ``file:row: message`` each, else its stderr."""
        errors = output.get("errors") if isinstance(output, dict) else None
        if not isinstance(errors, list) or not errors:
            return stderr.strip() or "no error output"
        lines: list[str] = []
        for err in errors:
            if not isinstance(err, dict):
                continue
            location = err.get("location") or {}
            where = (
                f"{cls._POLICY_FILE}:{location.get('row')}: "
                if isinstance(location, dict) and location.get("row")
                else ""
            )
            lines.append(f"{where}{err.get('message', err)}")
        return "; ".join(lines)

    @classmethod
    def __decision(cls, value: dict[str, Any], revision: str | None) -> PolicyDecision:
        violations = [
            *(cls.__finding(f, "deny") for f in cls.__set(value, "deny")),
            *(cls.__finding(f, "warn") for f in cls.__set(value, "warn")),
        ]
        # Rego sets have no order: sort so equal plans give equal reports.
        violations.sort(key=lambda v: (v.rule_id, v.resource or "", v.message))
        rules = cls.__set(value, "rules")
        if not all(isinstance(r, str) and r for r in rules):
            raise PolicyEvaluationError(
                message="`rules` must hold non-empty strings only",
                error_code=502,
            )
        return PolicyDecision(
            violations=violations,
            checked_rules=sorted({*rules, *(v.rule_id for v in violations)}),
            revision=revision,
        )

    @staticmethod
    def __set(value: dict[str, Any], key: str) -> list[Any]:
        items = value.get(key, [])
        if not isinstance(items, list):
            raise PolicyEvaluationError(
                message=f"`{key}` must be a set, got {type(items).__name__}",
                error_code=502,
            )
        return items

    @classmethod
    def __finding(cls, item: Any, kind: str) -> ComplianceViolation:
        if not isinstance(item, dict):
            raise PolicyEvaluationError(
                message=f"a `{kind}` finding must be an object, got {item!r}",
                error_code=502,
            )
        rule_id, message = item.get("rule_id"), item.get("message")
        resource = item.get("resource")
        if not (isinstance(rule_id, str) and rule_id):
            raise PolicyEvaluationError(
                message=f"a `{kind}` finding has no `rule_id`: {item!r}",
                error_code=502,
            )
        if not (isinstance(message, str) and message):
            raise PolicyEvaluationError(
                message=f"`{kind}` finding {rule_id} has no `message`",
                error_code=502,
            )
        if resource is not None and not isinstance(resource, str):
            raise PolicyEvaluationError(
                message=f"`resource` of `{kind}` finding {rule_id} must be a string",
                error_code=502,
            )
        severity: Literal["warning", "error", "critical"] = "warning"
        if kind == "deny":
            requested = item.get("severity", "error")
            if requested not in ("error", "critical"):
                raise PolicyEvaluationError(
                    message=(
                        f"`deny` finding {rule_id} has severity {requested!r}; "
                        + "expected 'error' or 'critical'"
                    ),
                    error_code=502,
                )
            severity = requested
        return ComplianceViolation(
            rule_id=rule_id,
            severity=severity,
            resource=resource,
            message=message,
            source="opa",
        )
