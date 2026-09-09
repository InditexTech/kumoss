# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""AWS: ambient static keys verified with STS, optional AssumeRole per
scope, and Resource Groups Tagging API listing across every enabled
region."""

from __future__ import annotations

import asyncio
import json
import logging
import os

from ..engine import CommandResult
from ..models import LoginError
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
        """Verify the static keys with STS.

        ``get-caller-identity`` needs no IAM permission, so the only way
        it fails is an invalid, revoked or expired key pair. The engine
        and the CLI keep inheriting the ambient keys; nothing is written
        to ``~/.aws``.
        """
        result = await _run(
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
        if not result.ok:
            raise LoginError({self.display_name: result.stderr.strip()})
        logger.info("AWS credentials verified for account %s", result.stdout.strip())

    async def scope_env(self, scope_id: str) -> dict[str, str]:
        """AssumeRole credentials for *scope_id*, or ``{}`` without a role.

        Raises ``RuntimeError`` (STS refused) or ``OSError`` (``aws`` CLI
        missing). Whether that is fatal depends on which other providers
        are ready, so ``CloudCli.scope_env`` decides, not this method.
        """
        if not self._config.aws_terraform_role_name:
            return {}
        return await self._assume_role(scope_id)

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
        regions: list[str | None] = [None]  # default region only
        if regions_result.ok:
            try:
                names = json.loads(regions_result.stdout)
            except json.JSONDecodeError:
                names = None
            # Anything but a list of names (e.g. an object, whose keys
            # sorted() would happily treat as regions) keeps the fallback.
            if isinstance(names, list) and all(isinstance(n, str) for n in names):
                regions = sorted(names)

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
                if not isinstance(data, dict):
                    raise TypeError(
                        f"expected a JSON object, got {type(data).__name__}"
                    )
                arns.extend(
                    r["ResourceARN"]
                    for r in data.get("ResourceTagMappingList", [])
                    if isinstance(r, dict) and "ResourceARN" in r
                )
                pagination_token = data.get("PaginationToken") or None
                if not pagination_token:
                    break
            return arns

        # TaskGroup (not gather) so the first failing region cancels its
        # siblings' paging loops instead of leaving them running to
        # completion after the result is already decided.
        failure: CommandResult | None = None
        tasks: list[asyncio.Task[list[str]]] = []
        try:
            async with asyncio.TaskGroup() as group:
                tasks = [group.create_task(_get_resources(r)) for r in regions]
        except* _AwsRegionError as region_errors:
            first = region_errors.exceptions[0]
            assert isinstance(first, _AwsRegionError)
            failure = _failure(
                f"get-resources failed in region '{first.region}': "
                f"{first.result.stderr}",
                first.result.exit_code,
            )
        except* (json.JSONDecodeError, KeyError, TypeError, AttributeError) as errs:
            failure = failure or _failure(
                f"Failed to parse AWS response: {errs.exceptions[0]}"
            )
        if failure is not None:
            return failure

        arns: list[str] = []
        for task in tasks:
            arns.extend(task.result())
        return _ids_result(arns)
