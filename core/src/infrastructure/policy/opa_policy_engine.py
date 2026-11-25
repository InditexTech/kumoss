# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Evaluates the compliance policies with the ``opa`` binary.

Two kinds of Langfuse prompt hold Rego v1 policies, fetched on every
evaluation so moving the environment label applies to the next session:

- ``general/policies/compliance``, ``package kumoss.compliance``: always
  evaluated; a missing one is an error.
- ``<provider>/policies/compliance``, ``package kumoss.providers.<provider>``:
  evaluated when the root module declares that provider; a provider
  without one is skipped.

All of them run in one ``opa eval`` process reading the input on stdin,
querying ``data.kumoss``; nothing stays running between sessions.

Decision contract of every package (all optional, a missing one counts as
empty):

- ``deny``: blocking findings, ``{"rule_id", "message", "resource"?,
  "severity"?}`` with severity ``error`` (the default) or ``critical``.
- ``warn``: non-blocking findings, the same shape without a severity;
  reported as ``warning``.
- ``rules``: every rule id the policy evaluates, passed or not.

Keys outside the contract are ignored. Anything else that is off — a
package a fetched policy does not define, a wrong type, a deny severity
outside the two — is a PolicyEvaluationError, never an empty decision.
"""

import asyncio
import json
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, Literal, cast, final, override

from src.domains.dto import ComplianceViolation, PolicyDecision
from src.domains.exceptions import PolicyEvaluationError
from src.domains.interfaces import IPolicyEngine
from src.infrastructure.exceptions import PromptFetchError
from src.infrastructure.templates._fetcher import remote_fetcher
from src.shared.config import system_config
from src.shared.logger import logging


@dataclass(frozen=True)
class _Policy:
    """One fetched policy: ``general`` or a provider type name."""

    scope: str
    text: str
    revision: str

    @property
    def prompt(self) -> str:
        return f"{self.scope}/policies/compliance"

    @property
    def file(self) -> str:
        """The file name OPA reports this policy's errors against."""
        return f"{self.scope}.rego"

    @property
    def package(self) -> str:
        if self.scope == OpaPolicyEngine.GENERAL_SCOPE:
            return "kumoss.compliance"
        return f"kumoss.providers.{self.scope}"

    def decision(self, kumoss: dict[str, Any]) -> Any:
        """This policy's package in the value of ``data.kumoss``."""
        if self.scope == OpaPolicyEngine.GENERAL_SCOPE:
            return kumoss.get("compliance")
        providers = kumoss.get("providers")
        return providers.get(self.scope) if isinstance(providers, dict) else None


def _where(location: Any, prompts: dict[str, str]) -> str:
    """``<prompt>:<row>: `` for an OPA error location, else nothing."""
    if not isinstance(location, dict):
        return ""
    fields = cast(dict[str, Any], location)
    if not fields.get("row"):
        return ""
    file = PurePath(str(fields.get("file") or "")).name
    return f"{prompts.get(file, file)}:{fields.get('row')}: "


@final
class OpaPolicyEngine(IPolicyEngine):
    GENERAL_SCOPE: str = "general"
    _BINARY: str = "opa"
    _QUERY: str = "data.kumoss"
    _INPUT_SCHEMA: str = "kumoss.compliance.input/v1"
    _POLICY_NAME: str = "compliance"
    _TIMEOUT_SECONDS: float = 30.0

    @override
    async def evaluate(
        self, plan_json: dict[str, Any], providers: Sequence[str]
    ) -> PolicyDecision:
        policies = [await self.__fetch(self.GENERAL_SCOPE)]
        for provider in dict.fromkeys(providers):
            policy = await self.__fetch(provider)
            if policy is not None:
                policies.append(policy)
        document = {
            "plan": plan_json,
            "kumoss": {"schema": self._INPUT_SCHEMA, "providers": list(providers)},
        }
        kumoss = await self.__eval(policies, json.dumps(document).encode())
        decision = self.__decision(kumoss, policies)
        logging.info(
            f"Compliance policies {', '.join(decision.revisions)}: "
            + f"{sum(v.blocking for v in decision.violations)} denied, "
            + f"{sum(not v.blocking for v in decision.violations)} warned"
        )
        return decision

    @override
    async def verify(self, providers: Sequence[str]) -> None:
        _ = await self.evaluate({"resource_changes": []}, providers)

    async def __fetch(self, scope: str) -> _Policy | None:
        """The policy of ``scope``; None for a provider without one."""
        try:
            text, revision = await remote_fetcher.fetch_versioned(
                prompt_name=self._POLICY_NAME,
                scope=scope,
                type="policies",
                tag=system_config.environment,
            )
        except PromptFetchError as e:
            if e.error_code == 404 and scope != self.GENERAL_SCOPE:
                return None
            raise PolicyEvaluationError(
                message=(
                    f"the policy {scope}/policies/compliance could not be "
                    + f"fetched from Langfuse: {e.message}"
                ),
                error_code=502,
            ) from e
        return _Policy(scope=scope, text=text, revision=revision)

    async def __eval(
        self, policies: Sequence[_Policy], document: bytes
    ) -> dict[str, Any]:
        """The value of ``data.kumoss``; raises when there is none."""
        with tempfile.TemporaryDirectory(prefix="kumoss-policy-") as tmp:
            data: list[str] = []
            for policy in policies:
                path = Path(tmp) / policy.file
                _ = path.write_text(policy.text, encoding="utf-8")
                data += ["--data", path.as_posix()]
            exit_code, stdout, stderr = await self.__run(
                "eval",
                "--stdin-input",
                "--strict-builtin-errors",
                "--format",
                "json",
                *data,
                self._QUERY,
                stdin=document,
            )

        try:
            output = json.loads(stdout) if stdout.strip() else {}
        except json.JSONDecodeError:
            output = None
        if exit_code != 0:
            raise PolicyEvaluationError(
                message=f"opa eval failed: {self.__errors(output, stderr, policies)}",
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
                message="the policies define no package under `kumoss`",
                error_code=502,
            ) from e
        if not isinstance(value, dict):
            raise PolicyEvaluationError(
                message=f"{self._QUERY} is not an object",
                error_code=502,
            )
        return cast(dict[str, Any], value)

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

    @staticmethod
    def __errors(output: Any, stderr: str, policies: Sequence[_Policy]) -> str:
        """OPA's errors, one ``<prompt>:row: message`` each, else its stderr.

        Runtime (``eval_*``) errors give only their code: their message may
        quote input values, and the plan carries secrets unmasked. Parse,
        compile and type errors come from the policy text and keep theirs.
        """
        errors = output.get("errors") if isinstance(output, dict) else None
        if not isinstance(errors, list) or not errors:
            return stderr.strip() or "no error output"
        prompts = {policy.file: policy.prompt for policy in policies}
        lines: list[str] = []
        for err in errors:
            if not isinstance(err, dict):
                continue
            where = _where(err.get("location"), prompts)
            code = err.get("code")
            if isinstance(code, str) and code.startswith("eval_"):
                lines.append(f"{where}{code}")
            else:
                lines.append(f"{where}{err.get('message', code)}")
        return "; ".join(lines)

    @classmethod
    def __decision(
        cls, kumoss: dict[str, Any], policies: Sequence[_Policy]
    ) -> PolicyDecision:
        violations: list[ComplianceViolation] = []
        rules: set[str] = set()
        for policy in policies:
            value = policy.decision(kumoss)
            if not isinstance(value, dict):
                raise PolicyEvaluationError(
                    message=f"{policy.prompt} defines no `package {policy.package}`",
                    error_code=502,
                )
            package = cast(dict[str, Any], value)
            violations += [
                *(cls.__finding(f, "deny") for f in cls.__set(package, "deny")),
                *(cls.__finding(f, "warn") for f in cls.__set(package, "warn")),
            ]
            declared = cls.__set(package, "rules")
            if not all(isinstance(r, str) and r for r in declared):
                raise PolicyEvaluationError(
                    message=f"`rules` of {policy.prompt} must hold non-empty strings only",
                    error_code=502,
                )
            rules.update(cast(list[str], declared))
        # Rego sets have no order: sort so equal plans give equal reports.
        violations.sort(key=lambda v: (v.rule_id, v.resource or "", v.message))
        return PolicyDecision(
            violations=violations,
            checked_rules=sorted({*rules, *(v.rule_id for v in violations)}),
            revisions=[policy.revision for policy in policies],
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

    @staticmethod
    def __shown(value: Any) -> str:
        """A rejected value fit for an error message: a short string as is,
        anything else by type only, so no plan value is echoed."""
        if isinstance(value, str) and len(value) <= 16:
            return repr(value)
        return f"of type {type(value).__name__}"

    @classmethod
    def __finding(cls, item: Any, kind: str) -> ComplianceViolation:
        if not isinstance(item, dict):
            raise PolicyEvaluationError(
                message=f"a `{kind}` finding must be an object, got a {type(item).__name__}",
                error_code=502,
            )
        rule_id, message = item.get("rule_id"), item.get("message")
        resource = item.get("resource")
        if not (isinstance(rule_id, str) and rule_id):
            raise PolicyEvaluationError(
                message=(
                    f"a `{kind}` finding has no string `rule_id` "
                    + f"(keys: {', '.join(sorted(cast(dict[str, Any], item))) or 'none'})"
                ),
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
                        f"`deny` finding {rule_id} has severity {cls.__shown(requested)}; "
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
