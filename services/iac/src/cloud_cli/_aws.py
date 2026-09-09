# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""AWS: ambient static keys, optional STS AssumeRole per scope, and
Resource Groups Tagging API listing across every enabled region."""

from __future__ import annotations

import asyncio
import json
import logging
import os

from ..engine import CommandResult
from ._base import CloudProvider, _failure, _ids_result, _run

logger = logging.getLogger(__name__)

_AWS_TAG_MAX_PAGES = 100


class _AwsRegionError(Exception):
    """Raised inside ``_get_resources`` to propagate per-region failures."""

    def __init__(self, region: str | None, result: CommandResult) -> None:
        self.region = region
        self.result = result


class AwsProvider(CloudProvider):
    name = "aws"
    display_name = "AWS"
    cli_binary = "aws"

    def credential_env(self) -> dict[str, str]:
        return {
            "AWS_ACCESS_KEY_ID": self._config.aws_access_key_id,
            "AWS_SECRET_ACCESS_KEY": self._config.aws_secret_access_key,
        }

    async def login(self) -> None:
        """No-op: the engine and the CLI inherit the ambient static keys."""

    async def scope_env(self, scope_id: str) -> dict[str, str]:
        if not self._config.aws_terraform_role_name:
            return {}
        try:
            return await self._assume_role(scope_id)
        except (RuntimeError, OSError) as exc:
            # Cross-cloud plans are not supported, so a non-AWS scope_id
            # (an Azure subscription, a GCP project) can only fail here.
            # That is expected; the job runs with the env of the provider
            # it actually targets.
            logger.debug("AWS AssumeRole skipped for scope %s: %s", scope_id, exc)
            return {}

    async def _assume_role(self, scope_id: str) -> dict[str, str]:
        """Assume ``arn:aws:iam::{scope_id}:{aws_terraform_role_name}``.

        The role name is the IAM resource path and must already carry the
        ``role/`` prefix (e.g. ``role/nebula-terraform``); it is appended
        verbatim. Returns the AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY and
        AWS_SESSION_TOKEN of the assumed role.
        """
        role_arn = f"arn:aws:iam::{scope_id}:{self._config.aws_terraform_role_name}"
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

        try:
            credentials = json.loads(result.stdout)["Credentials"]
            env = {
                "AWS_ACCESS_KEY_ID": credentials["AccessKeyId"],
                "AWS_SECRET_ACCESS_KEY": credentials["SecretAccessKey"],
                "AWS_SESSION_TOKEN": credentials["SessionToken"],
            }
        except (KeyError, TypeError, ValueError) as exc:
            # ValueError covers json.JSONDecodeError; callers rely on every
            # failure surfacing as RuntimeError.
            raise RuntimeError(
                f"Malformed STS AssumeRole response for {role_arn}: {exc!r}"
            ) from exc
        logger.info("AWS AssumeRole successful for %s", role_arn)
        return env

    async def list_resource_ids(self, scope_id: str) -> CommandResult:
        env: dict[str, str] | None = None

        if self._config.aws_terraform_role_name:
            try:
                assumed_creds = await self._assume_role(scope_id)
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
                    f"scope_id '{scope_id}' does not match the account of the "
                    f"service's AWS credentials ('{account}'); configure "
                    "AWS_TERRAFORM_ROLE_NAME for cross-account access or provide "
                    "a matching scope_id."
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
                sorted(json.loads(regions_result.stdout))
                if regions_result.ok
                else [None]
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
