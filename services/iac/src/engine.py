# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Thin async wrapper around the IaC engine CLI (OpenTofu or Terraform).

Just enough to drive `init`, `validate`, `plan`, `show`, `apply`,
`import`, and `state pull`, one command per call — the flag surface is
identical across both engines, so the caller only picks the binary.
Implementations that need more (state locking, custom backends, policy
as code) should extend this or substitute their own.
"""

from __future__ import annotations

import asyncio
import codecs
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_BUFFER_LIMIT = 10 * 1024 * 1024  # per-line StreamReader limit
_CHUNK_SIZE = 64 * 1024  # fallback read size once a line overruns the limit
_LOG_PREVIEW = 512  # chars of an oversized line echoed to the debug log

_timeout: int | None = None


class EngineTimeoutError(Exception):
    """Raised when an engine command exceeds the configured timeout."""


def set_timeout(seconds: int) -> None:
    global _timeout
    _timeout = seconds if seconds > 0 else None


@dataclass
class CommandResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int = 0


async def _read_stream(
    stream: asyncio.StreamReader, chunks: list[str], channel: str, label: str
) -> None:
    """Capture *stream* into *chunks*, echoing each line to the debug log.

    Lines are the unit of logging only; the captured output is what the
    job returns, so it must survive even when a single line exceeds
    ``_BUFFER_LIMIT`` (e.g. a provider dumping a one-line JSON
    diagnostic). ``readline()`` would *discard* the buffered data on
    overrun before raising ``ValueError``, so we use ``readuntil()``,
    whose ``LimitOverrunError`` leaves the data in place; we then drain
    the rest of the stream in fixed-size chunks and log only a preview.
    """
    while True:
        try:
            line = await stream.readuntil(b"\n")
        except asyncio.IncompleteReadError as exc:
            line = exc.partial  # EOF without trailing newline
            if not line:
                break
        except asyncio.LimitOverrunError:
            await _drain_oversized(stream, chunks, channel, label)
            return
        text = line.decode("utf-8", errors="replace").rstrip("\n")
        chunks.append(text + "\n")
        logger.debug("[%s] %s: %s", label, channel, text)
        if not line.endswith(b"\n"):
            break


async def _drain_oversized(
    stream: asyncio.StreamReader, chunks: list[str], channel: str, label: str
) -> None:
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    total = 0
    preview = ""
    while True:
        data = await stream.read(_CHUNK_SIZE)
        if not data:
            break
        total += len(data)
        text = decoder.decode(data)
        if len(preview) < _LOG_PREVIEW:
            preview += text[: _LOG_PREVIEW - len(preview)]
        chunks.append(text)
    chunks.append(decoder.decode(b"", final=True))
    logger.debug(
        "[%s] %s: line exceeded %d bytes; captured %d bytes unlogged. Preview: %s",
        label,
        channel,
        _BUFFER_LIMIT,
        total,
        preview,
    )


async def _run(
    binary: str,
    args: list[str],
    cwd: Path,
    *,
    stream_stdout: bool = True,
    env: dict[str, str] | None = None,
) -> CommandResult:
    label = args[0] if args else binary
    t0 = time.monotonic()

    proc = await asyncio.create_subprocess_exec(
        binary,
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=_BUFFER_LIMIT,
        env=env,
    )

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    async def _consume() -> None:
        tasks: list[asyncio.Task] = []
        if stream_stdout:
            tasks.append(
                asyncio.create_task(
                    _read_stream(proc.stdout, stdout_chunks, "stdout", label)
                )
            )
        else:
            tasks.append(asyncio.create_task(_bulk_read(proc.stdout, stdout_chunks)))
        tasks.append(
            asyncio.create_task(
                _read_stream(proc.stderr, stderr_chunks, "stderr", label)
            )
        )
        await asyncio.gather(*tasks)
        await proc.wait()

    try:
        if _timeout is not None:
            await asyncio.wait_for(_consume(), timeout=_timeout)
        else:
            await _consume()
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - t0
        logger.error(
            "%s %s timed out after %.1fs (limit=%ss) workspace=%s",
            binary,
            label,
            elapsed,
            _timeout,
            cwd,
        )
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        raise EngineTimeoutError(
            f"{binary} {label} timed out after {elapsed:.0f}s (limit={_timeout}s)"
        )
    except BaseException:
        # Reader/decoder failure: never leave the engine running detached.
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        raise

    exit_code = proc.returncode if proc.returncode is not None else -1
    elapsed = time.monotonic() - t0
    stdout = "".join(stdout_chunks)
    stderr = "".join(stderr_chunks)

    if exit_code == 0:
        logger.info(
            "%s %s succeeded elapsed=%.2fs workspace=%s", binary, label, elapsed, cwd
        )
    else:
        logger.warning(
            "%s %s failed exit_code=%d elapsed=%.2fs workspace=%s",
            binary,
            label,
            exit_code,
            elapsed,
            cwd,
        )

    return CommandResult(
        ok=exit_code == 0,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
    )


async def _bulk_read(stream: asyncio.StreamReader, chunks: list[str]) -> None:
    data = await stream.read(-1)
    chunks.append(data.decode("utf-8", errors="replace"))


def _plan_file_arg(plan_file: str) -> str:
    return f"./{plan_file}"


async def init(
    binary: str,
    cwd: Path,
    *,
    backend_config: str = "",
    env: dict[str, str] | None = None,
) -> CommandResult:
    args = ["init", "-no-color", "-input=false"]
    if backend_config:
        args.append(f"-backend-config={backend_config}")
    return await _run(binary, args, cwd, env=env)


async def validate(
    binary: str, cwd: Path, *, env: dict[str, str] | None = None
) -> CommandResult:
    return await _run(binary, ["validate", "-no-color"], cwd, env=env)


async def plan(
    binary: str,
    cwd: Path,
    targets: list[str],
    plan_file: str,
    *,
    env: dict[str, str] | None = None,
) -> CommandResult:
    args = ["plan", "-no-color", "-input=false", "-out", _plan_file_arg(plan_file)]
    for t in targets:
        args.extend(["-target", t])
    return await _run(binary, args, cwd, env=env)


async def show_plan_json(
    binary: str, cwd: Path, plan_file: str, *, env: dict[str, str] | None = None
) -> CommandResult:
    return await _run(
        binary,
        ["show", "-json", "-no-color", _plan_file_arg(plan_file)],
        cwd,
        stream_stdout=False,
        env=env,
    )


async def show_state_json(
    binary: str, cwd: Path, *, env: dict[str, str] | None = None
) -> CommandResult:
    return await _run(
        binary, ["show", "-json", "-no-color"], cwd, stream_stdout=False, env=env
    )


async def apply(
    binary: str, cwd: Path, plan_file: str, *, env: dict[str, str] | None = None
) -> CommandResult:
    return await _run(
        binary,
        [
            "apply",
            "-no-color",
            "-input=false",
            "-auto-approve",
            _plan_file_arg(plan_file),
        ],
        cwd,
        env=env,
    )


async def import_resource(
    binary: str,
    cwd: Path,
    address: str,
    resource_id: str,
    *,
    env: dict[str, str] | None = None,
) -> CommandResult:
    return await _run(
        binary,
        ["import", "-no-color", "-input=false", address, resource_id],
        cwd,
        env=env,
    )


async def state_pull(
    binary: str, cwd: Path, *, env: dict[str, str] | None = None
) -> CommandResult:
    return await _run(binary, ["state", "pull"], cwd, stream_stdout=False, env=env)


def extract_managed_resource_ids(state_json: str) -> list[str]:
    """Provider-assigned ids of every managed resource instance in a
    pulled state document; [] when the state is empty or unparsable."""
    try:
        state = json.loads(state_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(state, dict):
        return []
    ids: list[str] = []
    resources = state.get("resources") or []
    if not isinstance(resources, list):
        return []
    for resource in resources:
        if not isinstance(resource, dict) or resource.get("mode") != "managed":
            continue
        instances = resource.get("instances") or []
        if not isinstance(instances, list):
            continue
        for instance in instances:
            if not isinstance(instance, dict):
                continue
            rid = (instance.get("attributes") or {}).get("id")
            if rid:
                ids.append(rid)
    return ids
