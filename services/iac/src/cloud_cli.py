# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Async wrappers around the az / gcloud / aws CLIs.

Handles startup cloud authentication and scope-level resource listing
for ``POST /v1/import/scope-resource-ids``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

from .config import Config
from .engine import CommandResult

logger = logging.getLogger(__name__)

_last_login: float = 0.0
_login_lock = asyncio.Lock()


def needs_relogin(refresh_minutes: int) -> bool:
    if _last_login == 0.0:
        return True
    return (time.monotonic() - _last_login) > refresh_minutes * 60


# Provider value (contract vocabulary) → CLI binary it shells out to.
CLI_BINARIES = {"azure": "az", "gcp": "gcloud", "aws": "aws"}

_GRAPH_PAGE_SIZE = 1000
_GRAPH_MAX_PAGES = 100
_AWS_TAG_MAX_PAGES = 100


def cli_available(provider: str) -> bool:
    binary = CLI_BINARIES.get(provider)
    return binary is not None and shutil.which(binary) is not None


async def _run(args: list[str], *, env: dict[str, str] | None = None) -> CommandResult:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    return CommandResult(
        ok=proc.returncode == 0,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        exit_code=proc.returncode if proc.returncode is not None else -1,
    )


# ---------------------------------------------------------------------------
# Startup cloud authentication
# ---------------------------------------------------------------------------


async def cloud_login(config: Config) -> None:
    """Authenticate against cloud providers.

    Uses double-check locking: the first caller to find the token
    expired acquires the lock and re-authenticates; concurrent callers
    re-check inside the lock and skip if another task already refreshed.

    Each provider is guarded by its required env vars — missing vars
    skip that provider with an info log.  All configured providers are
    attempted independently; failures are collected and raised together
    so every broken credential surfaces in a single startup cycle.
    """
    global _last_login
    async with _login_lock:
        if not needs_relogin(config.cloud_login_refresh_min):
            logger.debug("cloud tokens still valid, skipping re-login")
            return

        errors: list[str] = []

        if (
            config.azure_client_id
            and config.azure_client_secret
            and config.azure_tenant_id
        ):
            try:
                await _az_login_sp(config)
            except RuntimeError as exc:
                logger.error("Azure login failed: %s", exc)
                errors.append(f"Azure: {exc}")
        else:
            logger.info(
                "Azure login skipped: ARM_CLIENT_ID, ARM_CLIENT_SECRET, "
                "and ARM_TENANT_ID not all set"
            )

        if config.google_application_credentials or config.google_credentials:
            try:
                await _gcloud_auth(config)
            except RuntimeError as exc:
                logger.error("GCP auth failed: %s", exc)
                errors.append(f"GCP: {exc}")
        else:
            logger.info(
                "GCP auth skipped: GOOGLE_APPLICATION_CREDENTIALS "
                "and GOOGLE_CREDENTIALS not set"
            )

        if os.environ.get("AWS_ACCESS_KEY_ID"):
            logger.info("AWS ambient credentials detected")
        else:
            logger.info("AWS auth skipped: no ambient credentials detected")

        if errors:
            raise RuntimeError("Cloud login failed for: " + "; ".join(errors))

        _last_login = time.monotonic()
        logger.info("cloud login completed")


async def ensure_cloud_login(config: Config) -> None:
    """Re-login if cloud tokens have expired.

    Intended for per-request lazy checks inside background jobs.
    No-op when tokens are still fresh.
    """
    if needs_relogin(config.cloud_login_refresh_min):
        await cloud_login(config)


async def _az_login_sp(config: Config) -> None:
    result = await _run(
        [
            "az",
            "login",
            "--service-principal",
            "-u",
            config.azure_client_id,
            "-p",
            config.azure_client_secret,
            "--tenant",
            config.azure_tenant_id,
            "--allow-no-subscriptions",
        ],
        env={**os.environ},
    )
    if not result.ok:
        raise RuntimeError(f"Azure login failed: {result.stderr}")
    logger.info("Azure CLI login successful")


async def _gcloud_auth(config: Config) -> None:
    key_file = config.google_application_credentials
    key_json = config.google_credentials

    tmp_key_path: Path | None = None
    try:
        if not key_file and key_json:
            tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
            tmp.write(key_json)
            tmp.close()
            tmp_key_path = Path(tmp.name)
            key_file = str(tmp_key_path)

        result = await _run(
            [
                "gcloud",
                "auth",
                "activate-service-account",
                f"--key-file={key_file}",
            ]
        )
        if not result.ok:
            raise RuntimeError(f"GCP auth failed: {result.stderr}")
        logger.info("GCP auth successful")
    finally:
        if tmp_key_path is not None:
            tmp_key_path.unlink(missing_ok=True)


async def aws_assume_role(scope_id: str, role_name: str) -> dict[str, str]:
    """Construct a role ARN from *scope_id* and *role_name*, then assume it.

    Returns a dict with AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and
    AWS_SESSION_TOKEN from the assumed role.
    """
    role_arn = f"arn:aws:iam::{scope_id}:{role_name}"
    result = await _run(
        [
            "aws",
            "sts",
            "assume-role",
            "--role-arn",
            role_arn,
            "--role-session-name",
            "nebula-iac",
            "--output",
            "json",
        ]
    )
    if not result.ok:
        raise RuntimeError(f"AWS AssumeRole failed for {role_arn}: {result.stderr}")

    data = json.loads(result.stdout)
    try:
        credentials = data["Credentials"]
        env = {
            "AWS_ACCESS_KEY_ID": credentials["AccessKeyId"],
            "AWS_SECRET_ACCESS_KEY": credentials["SecretAccessKey"],
            "AWS_SESSION_TOKEN": credentials["SessionToken"],
        }
    except KeyError as exc:
        raise RuntimeError(
            f"Malformed STS AssumeRole response for {role_arn}: missing {exc}"
        ) from exc
    logger.info("AWS AssumeRole successful for %s", role_arn)
    return env


# ---------------------------------------------------------------------------
# Scope resource listing
# ---------------------------------------------------------------------------


class _AwsRegionError(Exception):
    """Raised inside ``_get_resources`` to propagate per-region failures."""

    def __init__(self, region: str | None, result: CommandResult) -> None:
        self.region = region
        self.result = result


def _failure(stderr: str, exit_code: int = 1) -> CommandResult:
    return CommandResult(ok=False, stdout="", stderr=stderr, exit_code=exit_code)


def _ids_result(ids: list[str]) -> CommandResult:
    return CommandResult(ok=True, stdout=json.dumps(ids), stderr="", exit_code=0)


async def list_resource_ids(
    provider: str, scope_id: str, *, aws_terraform_role_name: str = ""
) -> CommandResult:
    """List the resource IDs in one cloud scope as a JSON array on stdout."""
    if provider == "azure":
        return await _list_azure(scope_id)
    if provider == "gcp":
        return await _list_gcp(scope_id)
    if provider == "aws":
        return await _list_aws(scope_id, aws_terraform_role_name)
    return _failure(f"Unsupported terraform_provider: {provider!r}", exit_code=2)


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

    if skip_token:
        return _failure(
            f"az graph query exceeded max pages ({_GRAPH_MAX_PAGES}); refusing to truncate results"
        )

    return _ids_result([row["id"] for row in rows if "id" in row])


async def _list_gcp(scope_id: str) -> CommandResult:
    """List GCP resources and IAM roles; returned IDs mix both types."""
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


async def _list_aws(scope_id: str, role_name: str = "") -> CommandResult:
    env: dict[str, str] | None = None

    if role_name:
        try:
            assumed_creds = await aws_assume_role(scope_id, role_name)
        except RuntimeError as exc:
            return _failure(str(exc))
        env = {**os.environ, **assumed_creds}
    else:
        # No role configured: verify scope_id matches the ambient account.
        identity_result = await _run(
            [
                "aws",
                "sts",
                "get-caller-identity",
                "--query",
                "Account",
                "--output",
                "text",
            ]
        )
        if not identity_result.ok:
            return _failure(identity_result.stderr, identity_result.exit_code)
        account = identity_result.stdout.strip()
        if account != scope_id:
            return _failure(
                f"scope_id '{scope_id}' does not match the account of the service's "
                f"AWS credentials ('{account}'); configure AWS_TERRAFORM_ROLE_NAME "
                "for cross-account access or provide a matching scope_id."
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
        ],
        env=env,
    )
    regions: list[str | None]
    try:
        regions = (
            sorted(json.loads(regions_result.stdout)) if regions_result.ok else [None]
        )
    except json.JSONDecodeError:
        regions = [None]  # fall back to the default region only

    async def _get_resources(region: str | None) -> list[str]:
        """Paginate ``get-resources`` in a single region."""
        arns: list[str] = []
        pagination_token: str | None = None
        for _ in range(_AWS_TAG_MAX_PAGES):
            command = ["aws", "resourcegroupstaggingapi", "get-resources"]
            if region:
                command.extend(["--region", region])
            if pagination_token:
                command.extend(["--starting-token", pagination_token])
            command.extend(["--output", "json"])
            result = await _run(command, env=env)
            if not result.ok:
                raise _AwsRegionError(region, result)
            data = json.loads(result.stdout)
            arns.extend(
                r["ResourceARN"]
                for r in data.get("ResourceTagMappingList", [])
                if "ResourceARN" in r
            )
            pagination_token = data.get("PaginationToken") or None
            if not pagination_token:
                break
        return arns

    try:
        region_results = await asyncio.gather(*(_get_resources(r) for r in regions))
    except _AwsRegionError as exc:
        return _failure(
            f"get-resources failed in region '{exc.region}': {exc.result.stderr}",
            exc.result.exit_code,
        )
    except (json.JSONDecodeError, KeyError) as exc:
        return _failure(f"Failed to parse AWS response: {exc}")

    arns: list[str] = []
    for region_arns in region_results:
        arns.extend(region_arns)
    return _ids_result(arns)
