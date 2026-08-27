# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Async wrappers around the az / gcloud / aws CLIs for scope listing.

Only what `POST /v1/import/scope-resource-ids` needs: list the resource
IDs that exist in one cloud scope. Authentication is ambient — the CLIs
use whatever credentials the service process already has (env vars,
mounted config, instance metadata); their own auth errors pass through
in `stderr` like any other command failure.
"""

from __future__ import annotations

import asyncio
import json
import shutil

from .terraform import CommandResult


# Provider value (contract vocabulary) → CLI binary it shells out to.
CLI_BINARIES = {"azure": "az", "gcp": "gcloud", "aws": "aws"}

_GRAPH_PAGE_SIZE = 1000
_GRAPH_MAX_PAGES = 100


def cli_available(provider: str) -> bool:
    return shutil.which(CLI_BINARIES[provider]) is not None


async def _run(args: list[str]) -> CommandResult:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    return CommandResult(
        ok=proc.returncode == 0,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        exit_code=proc.returncode if proc.returncode is not None else -1,
    )


def _failure(stderr: str, exit_code: int = 1) -> CommandResult:
    return CommandResult(ok=False, stdout="", stderr=stderr, exit_code=exit_code)


def _ids_result(ids: list[str]) -> CommandResult:
    return CommandResult(ok=True, stdout=json.dumps(ids), stderr="", exit_code=0)


async def list_resource_ids(provider: str, scope_id: str) -> CommandResult:
    """List the resource IDs in one cloud scope as a JSON array on stdout."""
    if provider == "azure":
        return await _list_azure(scope_id)
    if provider == "gcp":
        return await _list_gcp(scope_id)
    return await _list_aws(scope_id)


async def _list_azure(scope_id: str) -> CommandResult:
    # scope_id is caller-controlled; escape it so it cannot terminate
    # the KQL string literal and alter the query.
    quoted = scope_id.replace("\\", "\\\\").replace("'", "\\'")
    query = (
        f"resources | where id contains '{quoted}' | project id"
        f" | union (resourcecontainers | where id contains '{quoted}' | project id)"
    )
    # Resource Graph pages at 1000 rows; follow skip_token so larger
    # scopes are not silently truncated.
    rows: list[dict] = []
    skip_token: str | None = None
    for _ in range(_GRAPH_MAX_PAGES):
        command = [
            "az",
            "graph",
            "query",
            "-q",
            query,
            "--first",
            str(_GRAPH_PAGE_SIZE),
            "--output",
            "json",
        ]
        if skip_token:
            command.extend(["--skip-token", skip_token])
        result = await _run(command)
        if not result.ok:
            return _failure(result.stderr, result.exit_code)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            return _failure(f"az graph query returned unparsable JSON: {exc}")
        rows.extend(payload.get("data", []))
        skip_token = payload.get("skip_token")
        if not skip_token:
            break
    return _ids_result([row["id"] for row in rows if "id" in row])


async def _list_gcp(scope_id: str) -> CommandResult:
    resources_result, iam_result = await asyncio.gather(
        _run(
            [
                "gcloud",
                "asset",
                "search-all-resources",
                f"--scope=projects/{scope_id}",
                "--format=json",
            ]
        ),
        _run(
            [
                "gcloud",
                "asset",
                "search-all-iam-policies",
                f"--scope=projects/{scope_id}",
                "--format=json",
            ]
        ),
    )

    errors = []
    if not resources_result.ok:
        errors.append(f"Resources: {resources_result.stderr}")
    if not iam_result.ok:
        errors.append(f"IAM: {iam_result.stderr}")
    if errors:
        return _failure("\n".join(errors))

    try:
        raw_resources = json.loads(resources_result.stdout)
        raw_iam = json.loads(iam_result.stdout)
    except json.JSONDecodeError as exc:
        return _failure(f"gcloud returned unparsable JSON: {exc}")

    # gcloud --format=json emits an array, but tolerate the REST-style
    # {"results": [...]} wrapper too.
    assets = (
        raw_resources.get("results", raw_resources)
        if isinstance(raw_resources, dict)
        else raw_resources
    )
    ids = [a["name"] for a in assets if "name" in a]

    iam_policies = (
        raw_iam.get("results", raw_iam) if isinstance(raw_iam, dict) else raw_iam
    )
    for policy_entry in iam_policies:
        for binding in policy_entry.get("policy", {}).get("bindings", []):
            role = binding.get("role", "")
            if role and role not in ids:
                ids.append(role)

    return _ids_result(ids)


async def _list_aws(scope_id: str) -> CommandResult:
    # The Tagging API answers for the account the ambient credentials
    # belong to; verify it matches the requested scope rather than
    # silently listing a different account.
    identity_result = await _run(
        ["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"]
    )
    if not identity_result.ok:
        return _failure(identity_result.stderr, identity_result.exit_code)
    account = identity_result.stdout.strip()
    if account != scope_id:
        return _failure(
            f"scope_id '{scope_id}' does not match the account of the service's "
            f"AWS credentials ('{account}'); cross-account listing is not "
            "supported by the reference implementation."
        )

    # The Tagging API is regional: enumerate the account's enabled
    # regions and aggregate. Global resources (IAM, Route53, ...) are
    # exposed through us-east-1, which describe-regions always includes.
    regions_result = await _run(
        [
            "aws",
            "ec2",
            "describe-regions",
            "--query",
            "Regions[].RegionName",
            "--output",
            "json",
        ]
    )
    regions: list[str | None]
    try:
        regions = (
            sorted(json.loads(regions_result.stdout)) if regions_result.ok else [None]
        )
    except json.JSONDecodeError:
        regions = [None]  # fall back to the default region only

    async def _get_resources(region: str | None) -> CommandResult:
        command = ["aws", "resourcegroupstaggingapi", "get-resources"]
        if region:
            command.extend(["--region", region])
        command.extend(["--output", "json"])
        return await _run(command)

    results = await asyncio.gather(*(_get_resources(r) for r in regions))

    arns: list[str] = []
    try:
        for region, result in zip(regions, results):
            if not result.ok:
                return _failure(
                    f"get-resources failed in region '{region}': {result.stderr}",
                    result.exit_code,
                )
            data = json.loads(result.stdout)
            arns.extend(
                r["ResourceARN"] for r in data.get("ResourceTagMappingList", [])
            )
    except (json.JSONDecodeError, KeyError) as exc:
        return _failure(f"Failed to parse AWS response: {exc}")

    return _ids_result(arns)
