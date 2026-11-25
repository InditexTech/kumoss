# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Thin async wrapper around the IaC engine CLI (OpenTofu or Terraform).

`IacEngine` binds one engine binary (and the deployment's backend
configuration file, when it sets one) and drives `init`, `validate`,
`plan`, `show`, `apply`, `import` and `state pull`, one command per call
— the flag surface is identical across both engines. The instance holds
configuration only, never command or job state, so one can be shared or
built per request interchangeably. Implementations that need more (state
locking, custom backends, policy as code) should subclass this or
substitute their own.

Every command but `state pull` runs with the request's ``env`` added to
the service's own environment, and `plan` and `import` with its
``var_files`` as ``-var-file`` in order, then its ``vars`` as the last
one. Neither is interpreted here: which scope a
command runs against is whatever the caller put in them (see the
contract's "Environment and input variables").
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from collections.abc import Generator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar


logger = logging.getLogger("iac.engine")


@dataclass
class CommandResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int = 0


class _OutsideWorkspace(Exception):
    pass


@contextmanager
def _var_file_args(
    cwd: Path, var_files: Sequence[str], variables: Mapping[str, Any]
) -> Generator[list[str]]:
    """The ``-var-file`` arguments, valid while the context is open.

    ``var_files`` come first, in order; a file that resolves outside the
    workspace (through a symlink) raises ``_OutsideWorkspace``. Then
    ``variables``, written to an owner-only temporary file outside the
    workspace (the workspace may be committed or shared) and removed on
    exit, so they win.
    """
    root = cwd.resolve()
    args: list[str] = []
    for var_file in var_files:
        if not (cwd / var_file).resolve().is_relative_to(root):
            raise _OutsideWorkspace(var_file)
        args.append(f"-var-file={var_file}")
    if not variables:
        yield args
        return
    fd, path = tempfile.mkstemp(prefix="iac-vars-", suffix=".tfvars.json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dict(variables), f)
        yield [*args, f"-var-file={path}"]
    finally:
        Path(path).unlink(missing_ok=True)


class IacEngine:
    """One engine binary, invoked once per method call."""

    # Failure diagnostics are passed through verbatim in the job result;
    # the console log only carries a tail, to stay readable.
    _STDERR_LOG_LIMIT: ClassVar[int] = 500

    def __init__(self, binary: str, backend_config: str | None = None) -> None:
        self._binary: str = binary
        self._backend_config: str | None = backend_config

    async def init(self, cwd: Path, env: Mapping[str, str]) -> CommandResult:
        """Initialize the workspace, always reconfiguring the backend.

        ``-reconfigure`` binds the workspace to the configured backend
        without asking to migrate state out of a backend it was previously
        bound to — the prompt `-input=false` could not answer, which would
        otherwise turn a changed backend into a hard failure. State already
        in the configured backend is adopted, not discarded.
        """
        args = ["init", "-no-color", "-input=false", "-reconfigure"]
        if self._backend_config:
            args.append(f"-backend-config={self._backend_config}")
        return await self._run(args, cwd, env)

    async def validate(self, cwd: Path, env: Mapping[str, str]) -> CommandResult:
        return await self._run(["validate", "-no-color"], cwd, env)

    async def plan(
        self,
        cwd: Path,
        targets: list[str],
        plan_file: str,
        env: Mapping[str, str],
        var_files: Sequence[str],
        variables: Mapping[str, Any],
    ) -> CommandResult:
        args = ["plan", "-no-color", "-input=false", "-out", plan_file]
        for t in targets:
            args.extend(["-target", t])
        return await self._run_with_inputs(args, cwd, env, var_files, variables)

    async def show_plan_json(
        self, cwd: Path, plan_file: str, env: Mapping[str, str]
    ) -> CommandResult:
        return await self._run(["show", "-json", "-no-color", plan_file], cwd, env)

    async def apply(
        self, cwd: Path, plan_file: str, env: Mapping[str, str]
    ) -> CommandResult:
        return await self._run(
            ["apply", "-no-color", "-input=false", "-auto-approve", plan_file],
            cwd,
            env,
        )

    async def import_resource(
        self,
        cwd: Path,
        address: str,
        resource_id: str,
        env: Mapping[str, str],
        var_files: Sequence[str],
        variables: Mapping[str, Any],
    ) -> CommandResult:
        # Options must precede the positional address and id.
        return await self._run_with_inputs(
            ["import", "-no-color", "-input=false"],
            cwd,
            env,
            var_files,
            variables,
            positional=[address, resource_id],
        )

    async def _run_with_inputs(
        self,
        args: list[str],
        cwd: Path,
        env: Mapping[str, str],
        var_files: Sequence[str],
        variables: Mapping[str, Any],
        positional: Sequence[str] = (),
    ) -> CommandResult:
        try:
            with _var_file_args(cwd, var_files, variables) as var_args:
                return await self._run([*args, *var_args, *positional], cwd, env)
        except _OutsideWorkspace as exc:
            return CommandResult(
                ok=False,
                stdout="",
                stderr=f"var file {exc} resolves outside the workspace",
                exit_code=1,
            )

    async def state_pull(self, cwd: Path) -> CommandResult:
        return await self._run(["state", "pull"], cwd)

    async def _run(
        self, args: list[str], cwd: Path, env: Mapping[str, str] | None = None
    ) -> CommandResult:
        # Names only: the request's values may be secrets.
        logger.info(
            "run: %s %s (cwd=%s, env=%s)",
            self._binary,
            " ".join(args),
            cwd,
            sorted(env or {}),
        )
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            self._binary,
            *args,
            cwd=str(cwd),
            env=None if env is None else {**os.environ, **env},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        duration = time.monotonic() - started
        result = CommandResult(
            ok=proc.returncode == 0,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            exit_code=proc.returncode if proc.returncode is not None else -1,
        )
        if result.ok:
            logger.info(
                "done: %s %s — exit 0 in %.1fs", self._binary, args[0], duration
            )
        else:
            logger.warning(
                "failed: %s %s — exit %d in %.1fs; stderr tail: %s",
                self._binary,
                args[0],
                result.exit_code,
                duration,
                result.stderr[-self._STDERR_LOG_LIMIT :].strip() or "(empty)",
            )
        return result
