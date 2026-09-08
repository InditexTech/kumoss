# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the cloud CLI scope-listing wrappers.

Every subprocess call is patched — these verify command construction
(KQL escaping, Resource Graph pagination, region fan-out), response
parsing, and failure propagation, not the real CLIs.
"""

from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, patch

import pytest

from src import cloud_cli
from src.config import Config
from src.engine import CommandResult


def _ok(stdout: str) -> CommandResult:
    return CommandResult(ok=True, stdout=stdout, stderr="", exit_code=0)


def _err(stderr: str, exit_code: int = 1) -> CommandResult:
    return CommandResult(ok=False, stdout="", stderr=stderr, exit_code=exit_code)


@pytest.mark.asyncio
async def test_azure_lists_ids_and_escapes_scope() -> None:
    """scope_id is escaped before interpolation into the KQL literal so
    it cannot terminate the string and alter the query."""
    page = _ok(json.dumps({"data": [{"id": "id-1"}, {"id": "id-2"}]}))
    with patch(
        "src.cloud_cli._run", new_callable=AsyncMock, return_value=page
    ) as run_mock:
        result = await cloud_cli.list_resource_ids("azure", "sub' | project name")
    assert result.ok
    assert json.loads(result.stdout) == ["id-1", "id-2"]
    query = run_mock.await_args.args[0][4]
    assert "sub\\' | project name" in query
    assert "'sub' | project name'" not in query


@pytest.mark.asyncio
async def test_azure_follows_pagination() -> None:
    pages = [
        _ok(json.dumps({"data": [{"id": "id-1"}], "skip_token": "t1"})),
        _ok(json.dumps({"data": [{"id": "id-2"}]})),
    ]
    with patch(
        "src.cloud_cli._run", new_callable=AsyncMock, side_effect=pages
    ) as run_mock:
        result = await cloud_cli.list_resource_ids("azure", "sub-1")
    assert json.loads(result.stdout) == ["id-1", "id-2"]
    assert run_mock.await_count == 2
    second_command = run_mock.await_args_list[1].args[0]
    assert second_command[-2:] == ["--skip-token", "t1"]


@pytest.mark.asyncio
async def test_azure_cli_failure_passes_through() -> None:
    with patch(
        "src.cloud_cli._run",
        new_callable=AsyncMock,
        return_value=_err("az: please run 'az login'", 3),
    ):
        result = await cloud_cli.list_resource_ids("azure", "sub-1")
    assert not result.ok
    assert result.exit_code == 3
    assert result.stdout == ""
    assert "az login" in result.stderr


@pytest.mark.asyncio
async def test_gcp_merges_asset_names_and_iam_roles() -> None:
    responses = [
        _ok(json.dumps([{"name": "//compute/instances/i1"}, {"name": "//storage/b1"}])),
        _ok(
            json.dumps(
                [
                    {
                        "policy": {
                            "bindings": [
                                {"role": "roles/owner"},
                                {"role": ""},
                                {"role": "roles/owner"},
                            ]
                        }
                    }
                ]
            )
        ),
    ]
    with patch("src.cloud_cli._run", new_callable=AsyncMock, side_effect=responses):
        result = await cloud_cli.list_resource_ids("gcp", "proj-1")
    assert result.ok
    assert json.loads(result.stdout) == [
        "//compute/instances/i1",
        "//storage/b1",
        "roles/owner",
    ]


@pytest.mark.asyncio
async def test_gcp_reports_both_query_failures() -> None:
    responses = [_err("resources boom"), _err("iam boom")]
    with patch("src.cloud_cli._run", new_callable=AsyncMock, side_effect=responses):
        result = await cloud_cli.list_resource_ids("gcp", "proj-1")
    assert not result.ok
    assert "Resources: resources boom" in result.stderr
    assert "IAM: iam boom" in result.stderr


@pytest.mark.asyncio
async def test_aws_rejects_account_mismatch() -> None:
    with patch(
        "src.cloud_cli._run",
        new_callable=AsyncMock,
        return_value=_ok("123456789012\n"),
    ) as run_mock:
        result = await cloud_cli.list_resource_ids("aws", "999999999999")
    assert not result.ok
    assert "does not match the account" in result.stderr
    assert run_mock.await_count == 1  # stops before any listing calls


@pytest.mark.asyncio
async def test_aws_aggregates_arns_across_regions() -> None:
    responses = [
        _ok("123456789012\n"),  # sts get-caller-identity
        _ok(json.dumps(["us-east-1", "eu-west-1"])),  # describe-regions
        _ok(json.dumps({"ResourceTagMappingList": [{"ResourceARN": "arn:1"}]})),
        _ok(json.dumps({"ResourceTagMappingList": [{"ResourceARN": "arn:2"}]})),
    ]
    with patch(
        "src.cloud_cli._run", new_callable=AsyncMock, side_effect=responses
    ) as run_mock:
        result = await cloud_cli.list_resource_ids("aws", "123456789012")
    assert result.ok
    assert json.loads(result.stdout) == ["arn:1", "arn:2"]
    # Regions are queried in sorted order.
    region_commands = [call.args[0] for call in run_mock.await_args_list[2:]]
    assert ["--region", "eu-west-1"] == region_commands[0][3:5]
    assert ["--region", "us-east-1"] == region_commands[1][3:5]


@pytest.mark.asyncio
async def test_aws_falls_back_to_default_region_when_enumeration_fails() -> None:
    responses = [
        _ok("123456789012\n"),
        _err("ec2 not permitted"),
        _ok(json.dumps({"ResourceTagMappingList": [{"ResourceARN": "arn:1"}]})),
    ]
    with patch(
        "src.cloud_cli._run", new_callable=AsyncMock, side_effect=responses
    ) as run_mock:
        result = await cloud_cli.list_resource_ids("aws", "123456789012")
    assert result.ok
    assert json.loads(result.stdout) == ["arn:1"]
    fallback_command = run_mock.await_args_list[2].args[0]
    assert "--region" not in fallback_command


@pytest.mark.asyncio
async def test_aws_listing_failure_names_region() -> None:
    responses = [
        _ok("123456789012\n"),
        _ok(json.dumps(["us-east-1"])),
        _err("throttled", 254),
    ]
    with patch("src.cloud_cli._run", new_callable=AsyncMock, side_effect=responses):
        result = await cloud_cli.list_resource_ids("aws", "123456789012")
    assert not result.ok
    assert result.exit_code == 254
    assert "us-east-1" in result.stderr


# ---------------------------------------------------------------------------
# aws_assume_role
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aws_assume_role_success() -> None:
    sts_response = json.dumps({
        "Credentials": {
            "AccessKeyId": "AKID",
            "SecretAccessKey": "SECRET",
            "SessionToken": "TOKEN",
        }
    })
    with patch(
        "src.cloud_cli._run",
        new_callable=AsyncMock,
        return_value=_ok(sts_response),
    ):
        result = await cloud_cli.aws_assume_role("123456789012", "my-role")
    assert result == {
        "AWS_ACCESS_KEY_ID": "AKID",
        "AWS_SECRET_ACCESS_KEY": "SECRET",
        "AWS_SESSION_TOKEN": "TOKEN",
    }


@pytest.mark.asyncio
async def test_aws_assume_role_cli_failure() -> None:
    with (
        patch(
            "src.cloud_cli._run",
            new_callable=AsyncMock,
            return_value=_err("access denied"),
        ),
        pytest.raises(RuntimeError, match="AssumeRole failed"),
    ):
        await cloud_cli.aws_assume_role("123456789012", "my-role")


@pytest.mark.asyncio
async def test_aws_assume_role_malformed_response() -> None:
    with (
        patch(
            "src.cloud_cli._run",
            new_callable=AsyncMock,
            return_value=_ok(json.dumps({"unexpected": "shape"})),
        ),
        pytest.raises(RuntimeError, match="Malformed STS"),
    ):
        await cloud_cli.aws_assume_role("123456789012", "my-role")


# ---------------------------------------------------------------------------
# cli_available
# ---------------------------------------------------------------------------


def test_cli_available_known_provider_found() -> None:
    with patch("shutil.which", return_value="/usr/bin/az"):
        assert cloud_cli.cli_available("azure") is True


def test_cli_available_known_provider_not_found() -> None:
    with patch("shutil.which", return_value=None):
        assert cloud_cli.cli_available("aws") is False


def test_cli_available_unknown_provider() -> None:
    assert cloud_cli.cli_available("unknown-provider") is False


# ---------------------------------------------------------------------------
# needs_relogin
# ---------------------------------------------------------------------------


def test_needs_relogin_fresh_state() -> None:
    original = cloud_cli._last_login
    try:
        cloud_cli._last_login = 0.0
        assert cloud_cli.needs_relogin(45) is True
    finally:
        cloud_cli._last_login = original


def test_needs_relogin_recently_logged_in() -> None:
    original = cloud_cli._last_login
    try:
        cloud_cli._last_login = time.monotonic()
        assert cloud_cli.needs_relogin(45) is False
    finally:
        cloud_cli._last_login = original


def test_needs_relogin_expired() -> None:
    original = cloud_cli._last_login
    try:
        cloud_cli._last_login = time.monotonic() - 3600
        assert cloud_cli.needs_relogin(45) is True
    finally:
        cloud_cli._last_login = original


# ---------------------------------------------------------------------------
# AWS pagination (I2 fix)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aws_paginates_get_resources() -> None:
    """Verify _list_aws follows PaginationToken across pages."""
    responses = [
        _ok("123456789012\n"),  # sts get-caller-identity
        _ok(json.dumps(["us-east-1"])),  # describe-regions
        # page 1 with PaginationToken
        _ok(json.dumps({
            "ResourceTagMappingList": [{"ResourceARN": "arn:page1"}],
            "PaginationToken": "tok1",
        })),
        # page 2 without PaginationToken
        _ok(json.dumps({
            "ResourceTagMappingList": [{"ResourceARN": "arn:page2"}],
        })),
    ]
    with patch(
        "src.cloud_cli._run", new_callable=AsyncMock, side_effect=responses
    ) as run_mock:
        result = await cloud_cli.list_resource_ids("aws", "123456789012")
    assert result.ok
    assert json.loads(result.stdout) == ["arn:page1", "arn:page2"]
    # The third call (page 2) should include --starting-token
    page2_command = run_mock.await_args_list[3].args[0]
    assert "--starting-token" in page2_command
    assert "tok1" in page2_command


# ---------------------------------------------------------------------------
# cloud_login — independent provider checks
# ---------------------------------------------------------------------------


def _both_providers_config() -> Config:
    return Config(
        expected_token="",
        iac_binary="sh",
        azure_client_id="az-id",
        azure_client_secret="az-secret",
        azure_tenant_id="az-tenant",
        google_credentials='{"type": "service_account"}',
    )


@pytest.mark.asyncio
async def test_cloud_login_attempts_gcp_even_when_azure_fails() -> None:
    """Both providers are attempted independently; a failing Azure login
    does not prevent the GCP login from running."""
    original = cloud_cli._last_login
    try:
        cloud_cli._last_login = 0.0
        config = _both_providers_config()
        with (
            patch(
                "src.cloud_cli._az_login_sp",
                new_callable=AsyncMock,
                side_effect=RuntimeError("az login: bad credentials"),
            ),
            patch(
                "src.cloud_cli._gcloud_auth",
                new_callable=AsyncMock,
            ) as gcloud_mock,
            pytest.raises(RuntimeError, match="Cloud login failed"),
        ):
            await cloud_cli.cloud_login(config)
        gcloud_mock.assert_awaited_once_with(config)
    finally:
        cloud_cli._last_login = original


@pytest.mark.asyncio
async def test_cloud_login_reports_all_failures_combined() -> None:
    """When multiple providers fail, the error message includes all of them."""
    original = cloud_cli._last_login
    try:
        cloud_cli._last_login = 0.0
        config = _both_providers_config()
        with (
            patch(
                "src.cloud_cli._az_login_sp",
                new_callable=AsyncMock,
                side_effect=RuntimeError("az login: expired"),
            ),
            patch(
                "src.cloud_cli._gcloud_auth",
                new_callable=AsyncMock,
                side_effect=RuntimeError("gcloud: invalid key"),
            ),
            pytest.raises(RuntimeError, match="Cloud login failed") as exc_info,
        ):
            await cloud_cli.cloud_login(config)
        assert "Azure" in str(exc_info.value)
        assert "GCP" in str(exc_info.value)
    finally:
        cloud_cli._last_login = original


@pytest.mark.asyncio
async def test_cloud_login_succeeds_when_all_providers_ok() -> None:
    """When all configured providers login successfully, _last_login is set."""
    original = cloud_cli._last_login
    try:
        cloud_cli._last_login = 0.0
        config = _both_providers_config()
        with (
            patch("src.cloud_cli._az_login_sp", new_callable=AsyncMock),
            patch("src.cloud_cli._gcloud_auth", new_callable=AsyncMock),
        ):
            await cloud_cli.cloud_login(config)
        assert cloud_cli._last_login > 0.0
    finally:
        cloud_cli._last_login = original
