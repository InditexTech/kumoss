# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the ``cloud_cli`` package.

One section per provider class (readiness, login, scope env, resource
listing) and one for the ``CloudCli`` orchestrator (credential
validation, login/refresh, scope env merging, state/scope resource ids).

Every subprocess call is patched — these verify command construction
(KQL escaping, Resource Graph pagination, region fan-out), response
parsing, and failure propagation, not the real CLIs. Subprocess patches
target the ``_run`` name in the provider module that calls it.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.cloud_cli import PROVIDERS, CloudCli
from src.cloud_cli._aws import AwsProvider
from src.cloud_cli._azure import AzureProvider
from src.cloud_cli._gcp import GcpProvider
from src.config import Config
from src.engine import CommandResult
from src.models import CredentialError, LoginError, MissingCredentialError

_AZURE = {
    "azure_client_id": "az-id",
    "azure_client_secret": "az-secret",
    "azure_tenant_id": "az-tenant",
}
_AWS = {"aws_access_key_id": "AKIA-test", "aws_secret_access_key": "secret-test"}
_GCP_MISSING = "GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_CREDENTIALS"

_STS_CREDS = {
    "AWS_ACCESS_KEY_ID": "AKID",
    "AWS_SECRET_ACCESS_KEY": "SECRET",
    "AWS_SESSION_TOKEN": "TOKEN",
}


def _ok(stdout: str) -> CommandResult:
    return CommandResult(ok=True, stdout=stdout, stderr="", exit_code=0)


def _err(stderr: str, exit_code: int = 1) -> CommandResult:
    return CommandResult(ok=False, stdout="", stderr=stderr, exit_code=exit_code)


def _config(**overrides) -> Config:
    return Config(expected_token="", iac_binary="sh", **overrides)


def _both_providers_config() -> Config:
    return _config(**_AZURE, google_credentials='{"type": "service_account"}')


# ---------------------------------------------------------------------------
# AzureProvider
# ---------------------------------------------------------------------------


def test_azure_class_vars() -> None:
    assert AzureProvider.name == "azure"
    assert AzureProvider.display_name == "Azure"
    assert AzureProvider.cli_binary == "az"


def test_azure_readiness_empty() -> None:
    provider = AzureProvider(_config())
    assert provider.missing_env() == [
        "ARM_CLIENT_ID",
        "ARM_CLIENT_SECRET",
        "ARM_TENANT_ID",
    ]
    assert provider.is_configured() is False
    assert provider.is_ready() is False


def test_azure_readiness_partial() -> None:
    provider = AzureProvider(_config(azure_client_id="az-id"))
    assert provider.missing_env() == ["ARM_CLIENT_SECRET", "ARM_TENANT_ID"]
    assert provider.is_configured() is True
    assert provider.is_ready() is False


def test_azure_readiness_complete() -> None:
    provider = AzureProvider(_config(**_AZURE))
    assert provider.missing_env() == []
    assert provider.is_configured() is True
    assert provider.is_ready() is True


@pytest.mark.asyncio
async def test_azure_scope_env_injects_subscription() -> None:
    env = await AzureProvider(_config(**_AZURE)).scope_env("sub-1")
    assert env == {"ARM_SUBSCRIPTION_ID": "sub-1"}


@pytest.mark.asyncio
async def test_azure_login_runs_service_principal_login() -> None:
    with patch(
        "src.cloud_cli._azure._run", new_callable=AsyncMock, return_value=_ok("")
    ) as run_mock:
        await AzureProvider(_config(**_AZURE)).login()
    argv = run_mock.await_args.args[0]
    assert argv[:3] == ["az", "login", "--service-principal"]
    assert argv[argv.index("-u") + 1] == "az-id"
    assert argv[argv.index("-p") + 1] == "az-secret"
    assert argv[argv.index("--tenant") + 1] == "az-tenant"
    assert "--allow-no-subscriptions" in argv


@pytest.mark.asyncio
async def test_azure_login_failure_raises_login_error() -> None:
    with (
        patch(
            "src.cloud_cli._azure._run",
            new_callable=AsyncMock,
            return_value=_err("bad secret"),
        ),
        pytest.raises(
            LoginError, match="Cloud login failed for: Azure: bad secret"
        ) as exc_info,
    ):
        await AzureProvider(_config(**_AZURE)).login()
    assert exc_info.value.failures == {"Azure": "bad secret"}


@pytest.mark.asyncio
async def test_azure_lists_ids_and_escapes_scope() -> None:
    """scope_id is escaped before interpolation into the KQL literal so
    it cannot terminate the string and alter the query."""
    page = _ok(json.dumps({"data": [{"id": "id-1"}, {"id": "id-2"}]}))
    with patch(
        "src.cloud_cli._azure._run", new_callable=AsyncMock, return_value=page
    ) as run_mock:
        result = await AzureProvider(_config()).list_resource_ids("sub' | project name")
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
        "src.cloud_cli._azure._run", new_callable=AsyncMock, side_effect=pages
    ) as run_mock:
        result = await AzureProvider(_config()).list_resource_ids("sub-1")
    assert json.loads(result.stdout) == ["id-1", "id-2"]
    assert run_mock.await_count == 2
    second_command = run_mock.await_args_list[1].args[0]
    assert second_command[-2:] == ["--skip-token", "t1"]


@pytest.mark.asyncio
async def test_azure_cli_failure_passes_through() -> None:
    with patch(
        "src.cloud_cli._azure._run",
        new_callable=AsyncMock,
        return_value=_err("az: please run 'az login'", 3),
    ):
        result = await AzureProvider(_config()).list_resource_ids("sub-1")
    assert not result.ok
    assert result.exit_code == 3
    assert result.stdout == ""
    assert "az login" in result.stderr


# ---------------------------------------------------------------------------
# GcpProvider
# ---------------------------------------------------------------------------


def test_gcp_class_vars() -> None:
    assert GcpProvider.name == "gcp"
    assert GcpProvider.display_name == "GCP"
    assert GcpProvider.cli_binary == "gcloud"


def test_gcp_readiness_empty() -> None:
    provider = GcpProvider(_config())
    assert provider.missing_env() == [_GCP_MISSING]
    assert provider.is_configured() is False
    assert provider.is_ready() is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"google_application_credentials": "/key.json"},
        {"google_credentials": "{}"},
    ],
    ids=["key-file", "inline-json"],
)
def test_gcp_is_ready_with_either_var_alone(overrides: dict) -> None:
    provider = GcpProvider(_config(**overrides))
    assert provider.missing_env() == []
    assert provider.is_configured() is True
    assert provider.is_ready() is True


@pytest.mark.asyncio
async def test_gcp_scope_env_injects_project() -> None:
    env = await GcpProvider(_config(google_credentials="{}")).scope_env("proj-1")
    assert env == {"GOOGLE_PROJECT": "proj-1"}


@pytest.mark.asyncio
async def test_gcp_login_uses_key_file_directly() -> None:
    with patch(
        "src.cloud_cli._gcp._run", new_callable=AsyncMock, return_value=_ok("")
    ) as run_mock:
        await GcpProvider(_config(google_application_credentials="/key.json")).login()
    argv = run_mock.await_args.args[0]
    assert argv[:3] == ["gcloud", "auth", "activate-service-account"]
    assert "--key-file=/key.json" in argv


@pytest.mark.asyncio
async def test_gcp_login_writes_and_removes_temp_key_for_inline_json() -> None:
    key_json = '{"type": "service_account"}'
    seen: dict[str, object] = {}

    async def fake_run(argv: list[str], **_: object) -> CommandResult:
        key_path = Path(
            next(a for a in argv if a.startswith("--key-file=")).split("=", 1)[1]
        )
        seen["path"] = key_path
        seen["content"] = key_path.read_text()
        return _ok("")

    with patch("src.cloud_cli._gcp._run", side_effect=fake_run):
        await GcpProvider(_config(google_credentials=key_json)).login()
    assert seen["content"] == key_json
    assert not Path(seen["path"]).exists()  # temp key removed afterwards


@pytest.mark.asyncio
async def test_gcp_login_failure_raises_login_error() -> None:
    with (
        patch(
            "src.cloud_cli._gcp._run",
            new_callable=AsyncMock,
            return_value=_err("invalid key"),
        ),
        pytest.raises(LoginError, match="Cloud login failed for: GCP: invalid key"),
    ):
        await GcpProvider(_config(google_application_credentials="/key.json")).login()


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
    with patch(
        "src.cloud_cli._gcp._run", new_callable=AsyncMock, side_effect=responses
    ):
        result = await GcpProvider(_config()).list_resource_ids("proj-1")
    assert result.ok
    assert json.loads(result.stdout) == [
        "//compute/instances/i1",
        "//storage/b1",
        "roles/owner",
    ]


@pytest.mark.asyncio
async def test_gcp_reports_both_query_failures() -> None:
    responses = [_err("resources boom"), _err("iam boom")]
    with patch(
        "src.cloud_cli._gcp._run", new_callable=AsyncMock, side_effect=responses
    ):
        result = await GcpProvider(_config()).list_resource_ids("proj-1")
    assert not result.ok
    assert "Resources: resources boom" in result.stderr
    assert "IAM: iam boom" in result.stderr


@pytest.mark.asyncio
async def test_gcp_listing_rejects_unexpected_json_shape() -> None:
    """Valid JSON that is not the documented asset/policy shape must end
    as a listing failure, not an AttributeError that fails the job 500."""
    responses = [_ok(json.dumps([{"name": "r1"}])), _ok(json.dumps(["not-a-dict"]))]
    with patch(
        "src.cloud_cli._gcp._run", new_callable=AsyncMock, side_effect=responses
    ):
        result = await GcpProvider(_config(google_credentials="{}")).list_resource_ids(
            "proj-1"
        )
    assert not result.ok
    assert "unexpected JSON shape" in result.stderr


# ---------------------------------------------------------------------------
# AwsProvider
# ---------------------------------------------------------------------------


def test_aws_class_vars() -> None:
    assert AwsProvider.name == "aws"
    assert AwsProvider.display_name == "AWS"
    assert AwsProvider.cli_binary == "aws"


def test_aws_readiness_empty() -> None:
    provider = AwsProvider(_config())
    assert provider.missing_env() == ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
    assert provider.is_configured() is False
    assert provider.is_ready() is False


def test_aws_readiness_partial() -> None:
    """A key ID without its secret is rejected by both the CLI and the
    provider, so it must count as configured-but-not-ready."""
    provider = AwsProvider(_config(aws_access_key_id="AKIA-test"))
    assert provider.missing_env() == ["AWS_SECRET_ACCESS_KEY"]
    assert provider.is_configured() is True
    assert provider.is_ready() is False


def test_aws_readiness_complete() -> None:
    provider = AwsProvider(_config(**_AWS))
    assert provider.missing_env() == []
    assert provider.is_configured() is True
    assert provider.is_ready() is True


@pytest.mark.asyncio
async def test_aws_scope_env_without_role_is_empty() -> None:
    with patch.object(AwsProvider, "_assume_role", new_callable=AsyncMock) as assume:
        env = await AwsProvider(_config(**_AWS)).scope_env("123456789012")
    assert env == {}
    assume.assert_not_awaited()


@pytest.mark.asyncio
async def test_aws_assume_role_success() -> None:
    sts_response = json.dumps(
        {
            "Credentials": {
                "AccessKeyId": "AKID",
                "SecretAccessKey": "SECRET",
                "SessionToken": "TOKEN",
            }
        }
    )
    with patch(
        "src.cloud_cli._aws._run",
        new_callable=AsyncMock,
        return_value=_ok(sts_response),
    ) as run:
        result = await AwsProvider(
            _config(**_AWS, aws_terraform_role_name="role/my-role")
        )._assume_role("123456789012")
    assert result == _STS_CREDS
    argv = run.await_args.args[0]
    assert argv[argv.index("--role-arn") + 1] == (
        "arn:aws:iam::123456789012:role/my-role"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("role_name", ["my-role", "role/my-role"])
async def test_aws_assume_role_failure_names_role_verbatim(role_name: str) -> None:
    """The service does not inject ``role/``; the operator supplies the
    full IAM resource path in AWS_TERRAFORM_ROLE_NAME. A failing STS call
    surfaces as RuntimeError naming the exact ARN that was attempted."""
    expected_arn = f"arn:aws:iam::123456789012:{role_name}"
    with patch(
        "src.cloud_cli._aws._run",
        new_callable=AsyncMock,
        return_value=_err("access denied"),
    ) as run:
        with pytest.raises(
            RuntimeError, match=f"AssumeRole failed for {re.escape(expected_arn)}"
        ):
            await AwsProvider(
                _config(**_AWS, aws_terraform_role_name=role_name)
            )._assume_role("123456789012")
    argv = run.await_args.args[0]
    assert argv[argv.index("--role-arn") + 1] == expected_arn


@pytest.mark.asyncio
async def test_aws_assume_role_malformed_response() -> None:
    with (
        patch(
            "src.cloud_cli._aws._run",
            new_callable=AsyncMock,
            return_value=_ok(json.dumps({"unexpected": "shape"})),
        ),
        pytest.raises(RuntimeError, match="Malformed STS"),
    ):
        await AwsProvider(
            _config(**_AWS, aws_terraform_role_name="role/my-role")
        )._assume_role("123456789012")


@pytest.mark.asyncio
async def test_aws_rejects_account_mismatch() -> None:
    with patch(
        "src.cloud_cli._aws._run",
        new_callable=AsyncMock,
        return_value=_ok("123456789012\n"),
    ) as run_mock:
        result = await AwsProvider(_config()).list_resource_ids("999999999999")
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
        "src.cloud_cli._aws._run", new_callable=AsyncMock, side_effect=responses
    ) as run_mock:
        result = await AwsProvider(_config()).list_resource_ids("123456789012")
    assert result.ok
    assert json.loads(result.stdout) == ["arn:1", "arn:2"]
    # Regions are queried in sorted order.
    region_commands = [call.args[0] for call in run_mock.await_args_list[2:]]
    assert ["--region", "eu-west-1"] == region_commands[0][3:5]
    assert ["--region", "us-east-1"] == region_commands[1][3:5]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "regions_response",
    [
        _err("ec2 not permitted"),
        _ok(json.dumps({"Regions": "unexpected"})),  # valid JSON, wrong shape
    ],
    ids=["describe-regions-fails", "describe-regions-not-a-list"],
)
async def test_aws_falls_back_to_default_region_when_enumeration_is_unusable(
    regions_response: CommandResult,
) -> None:
    responses = [
        _ok("123456789012\n"),
        regions_response,
        _ok(json.dumps({"ResourceTagMappingList": [{"ResourceARN": "arn:1"}]})),
    ]
    with patch(
        "src.cloud_cli._aws._run", new_callable=AsyncMock, side_effect=responses
    ) as run_mock:
        result = await AwsProvider(_config()).list_resource_ids("123456789012")
    assert result.ok
    assert json.loads(result.stdout) == ["arn:1"]
    fallback_command = run_mock.await_args_list[2].args[0]
    assert "--region" not in fallback_command


@pytest.mark.asyncio
async def test_aws_listing_rejects_unexpected_page_shape() -> None:
    responses = [
        _ok("123456789012\n"),
        _ok(json.dumps(["us-east-1"])),
        _ok(json.dumps(["not", "an", "object"])),
    ]
    with patch(
        "src.cloud_cli._aws._run", new_callable=AsyncMock, side_effect=responses
    ):
        result = await AwsProvider(_config()).list_resource_ids("123456789012")
    assert not result.ok
    assert "Failed to parse AWS response" in result.stderr


@pytest.mark.asyncio
async def test_aws_listing_failure_names_region() -> None:
    responses = [
        _ok("123456789012\n"),
        _ok(json.dumps(["us-east-1"])),
        _err("throttled", 254),
    ]
    with patch(
        "src.cloud_cli._aws._run", new_callable=AsyncMock, side_effect=responses
    ):
        result = await AwsProvider(_config()).list_resource_ids("123456789012")
    assert not result.ok
    assert result.exit_code == 254
    assert "us-east-1" in result.stderr


@pytest.mark.asyncio
async def test_aws_paginates_get_resources() -> None:
    """Verify the listing follows PaginationToken across pages."""
    responses = [
        _ok("123456789012\n"),  # sts get-caller-identity
        _ok(json.dumps(["us-east-1"])),  # describe-regions
        # page 1 with PaginationToken
        _ok(
            json.dumps(
                {
                    "ResourceTagMappingList": [{"ResourceARN": "arn:page1"}],
                    "PaginationToken": "tok1",
                }
            )
        ),
        # page 2 without PaginationToken
        _ok(
            json.dumps(
                {
                    "ResourceTagMappingList": [{"ResourceARN": "arn:page2"}],
                }
            )
        ),
    ]
    with patch(
        "src.cloud_cli._aws._run", new_callable=AsyncMock, side_effect=responses
    ) as run_mock:
        result = await AwsProvider(_config()).list_resource_ids("123456789012")
    assert result.ok
    assert json.loads(result.stdout) == ["arn:page1", "arn:page2"]
    # The third call (page 2) should include --starting-token
    page2_command = run_mock.await_args_list[3].args[0]
    assert "--starting-token" in page2_command
    assert "tok1" in page2_command


@pytest.mark.asyncio
async def test_aws_listing_with_role_assumes_and_skips_identity_check() -> None:
    """With a role configured the account check is replaced by AssumeRole
    and the assumed credentials are passed to every listing call."""
    responses = [
        _ok(json.dumps(["us-east-1"])),  # describe-regions (no identity call)
        _ok(json.dumps({"ResourceTagMappingList": [{"ResourceARN": "arn:1"}]})),
    ]
    with (
        patch.object(
            AwsProvider,
            "_assume_role",
            new_callable=AsyncMock,
            return_value=_STS_CREDS,
        ) as assume,
        patch(
            "src.cloud_cli._aws._run", new_callable=AsyncMock, side_effect=responses
        ) as run_mock,
    ):
        result = await AwsProvider(
            _config(**_AWS, aws_terraform_role_name="role/nebula")
        ).list_resource_ids("123456789012")
    assert result.ok
    assert json.loads(result.stdout) == ["arn:1"]
    assume.assert_awaited_once_with("123456789012")
    assert run_mock.await_args_list[0].args[0][:3] == ["aws", "ec2", "describe-regions"]
    for call in run_mock.await_args_list:
        assert call.kwargs["env"]["AWS_SESSION_TOKEN"] == "TOKEN"


@pytest.mark.asyncio
async def test_aws_listing_reports_assume_role_failure() -> None:
    with (
        patch.object(
            AwsProvider,
            "_assume_role",
            new_callable=AsyncMock,
            side_effect=RuntimeError("AWS AssumeRole failed for arn: denied"),
        ),
        patch("src.cloud_cli._aws._run", new_callable=AsyncMock) as run_mock,
    ):
        result = await AwsProvider(
            _config(**_AWS, aws_terraform_role_name="role/nebula")
        ).list_resource_ids("123456789012")
    assert not result.ok
    assert "AssumeRole failed" in result.stderr
    run_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# CloudCli — providers, credential validation, readiness
# ---------------------------------------------------------------------------


def test_providers_order() -> None:
    assert PROVIDERS == (AzureProvider, GcpProvider, AwsProvider)


def test_validate_credentials_passes_with_zero_configured_providers() -> None:
    assert CloudCli(_config()).validate_credentials() is None


def test_validate_credentials_passes_with_one_complete_provider() -> None:
    assert CloudCli(_config(**_AZURE)).validate_credentials() is None


def test_validate_credentials_aggregates_every_partial_provider() -> None:
    """Two partial providers raise once, naming both, so the operator
    fixes the deployment in one pass."""
    with pytest.raises(MissingCredentialError) as exc_info:
        CloudCli(
            _config(azure_client_id="az-id", aws_access_key_id="AKIA-test")
        ).validate_credentials()
    assert exc_info.value.missing == {
        "Azure": ["ARM_CLIENT_SECRET", "ARM_TENANT_ID"],
        "AWS": ["AWS_SECRET_ACCESS_KEY"],
    }
    assert "Azure" in str(exc_info.value)
    assert "AWS" in str(exc_info.value)


def test_ready_providers_logs_each_skipped_provider(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="src.cloud_cli._cli")
    ready = CloudCli(_config(**_AZURE)).ready_providers()
    assert [type(p) for p in ready] == [AzureProvider]
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    gcp_lines = [m for m in messages if "GCP" in m]
    aws_lines = [m for m in messages if "AWS" in m]
    assert len(gcp_lines) == 1 and _GCP_MISSING in gcp_lines[0]
    assert len(aws_lines) == 1
    assert "AWS_ACCESS_KEY_ID" in aws_lines[0]
    assert "AWS_SECRET_ACCESS_KEY" in aws_lines[0]


# ---------------------------------------------------------------------------
# CloudCli — cli_available
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("provider", "binary"), [("azure", "az"), ("gcp", "gcloud"), ("aws", "aws")]
)
def test_cli_available_looks_up_the_provider_binary(provider: str, binary: str) -> None:
    with patch("shutil.which", return_value=f"/usr/bin/{binary}") as which:
        assert CloudCli(_config()).cli_available(provider) is True
    which.assert_called_once_with(binary)


def test_cli_available_known_provider_not_found() -> None:
    with patch("shutil.which", return_value=None) as which:
        assert CloudCli(_config()).cli_available("aws") is False
    which.assert_called_once_with("aws")


def test_cli_available_unknown_provider() -> None:
    assert CloudCli(_config()).cli_available("unknown-provider") is False


def test_cli_binary_names_the_provider_binary() -> None:
    """The submit-time 503 names the binary the operator must install."""
    cloud = CloudCli(_config())
    assert cloud.cli_binary("gcp") == "gcloud"
    assert cloud.cli_binary("azure") == "az"


def test_cli_binary_unknown_provider_echoes_name() -> None:
    assert CloudCli(_config()).cli_binary("oci") == "oci"


# ---------------------------------------------------------------------------
# CloudCli — needs_relogin
# ---------------------------------------------------------------------------


def test_needs_relogin_recently_logged_in() -> None:
    cloud = CloudCli(_config(cloud_login_refresh_min=45))
    cloud._last_login = time.monotonic()
    assert cloud.needs_relogin() is False


def test_needs_relogin_expired() -> None:
    cloud = CloudCli(_config(cloud_login_refresh_min=45))
    cloud._last_login = time.monotonic() - 3600
    assert cloud.needs_relogin() is True


# ---------------------------------------------------------------------------
# CloudCli — login: independent provider checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cloud_login_attempts_gcp_even_when_azure_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Both providers are attempted independently; a failing Azure login
    does not prevent the GCP login from running, and only the provider
    that actually succeeded is logged as successful."""
    caplog.set_level(logging.INFO, logger="src.cloud_cli._cli")
    cloud = CloudCli(_both_providers_config())
    with (
        patch.object(
            AzureProvider,
            "login",
            new_callable=AsyncMock,
            side_effect=LoginError({"Azure": "az login: bad credentials"}),
        ),
        patch.object(GcpProvider, "login", new_callable=AsyncMock) as gcloud_mock,
        pytest.raises(LoginError, match="Cloud login failed"),
    ):
        await cloud.login()
    gcloud_mock.assert_awaited_once()
    messages = [r.getMessage() for r in caplog.records]
    assert not [m for m in messages if m.startswith("Azure login successful")]
    assert [m for m in messages if m.startswith("GCP login successful")]


@pytest.mark.asyncio
async def test_cloud_login_reports_all_failures_combined() -> None:
    """When multiple providers fail, the error message includes all of them."""
    cloud = CloudCli(_both_providers_config())
    with (
        patch.object(
            AzureProvider,
            "login",
            new_callable=AsyncMock,
            side_effect=LoginError({"Azure": "az login: expired"}),
        ),
        patch.object(
            GcpProvider,
            "login",
            new_callable=AsyncMock,
            side_effect=LoginError({"GCP": "gcloud: invalid key"}),
        ),
        pytest.raises(LoginError, match="Cloud login failed") as exc_info,
    ):
        await cloud.login()
    assert exc_info.value.failures == {
        "Azure": "az login: expired",
        "GCP": "gcloud: invalid key",
    }


@pytest.mark.asyncio
async def test_cloud_login_succeeds_when_all_providers_ok() -> None:
    """When all configured providers login successfully, _last_login is set."""
    cloud = CloudCli(_both_providers_config())
    with (
        patch.object(AzureProvider, "login", new_callable=AsyncMock),
        patch.object(GcpProvider, "login", new_callable=AsyncMock),
    ):
        await cloud.login()
    assert cloud._last_login > 0.0


@pytest.mark.asyncio
async def test_cloud_login_logs_each_successful_provider(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Operators reading the boot log should see one line per provider
    the service is authenticated against, AWS included."""
    caplog.set_level(logging.INFO, logger="src.cloud_cli._cli")
    cloud = CloudCli(_config(**_AZURE, **_AWS, google_credentials="{}"))
    with (
        patch.object(AzureProvider, "login", new_callable=AsyncMock),
        patch.object(GcpProvider, "login", new_callable=AsyncMock),
    ):
        await cloud.login()
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    for name in ("Azure", "GCP", "AWS"):
        assert [m for m in messages if m.startswith(f"{name} login successful")], name


@pytest.mark.asyncio
async def test_cloud_login_skips_when_tokens_are_fresh() -> None:
    cloud = CloudCli(_both_providers_config())
    cloud._last_login = time.monotonic()
    with (
        patch.object(AzureProvider, "login", new_callable=AsyncMock) as az,
        patch.object(GcpProvider, "login", new_callable=AsyncMock) as gcloud,
    ):
        await cloud.login()
        await cloud.ensure_login()
    az.assert_not_awaited()
    gcloud.assert_not_awaited()


# ---------------------------------------------------------------------------
# CloudCli — login: retry of transient refresh failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_relogin_retries_only_the_failed_provider_then_succeeds() -> None:
    """A transient Azure failure during the per-job refresh is retried
    with backoff; GCP, which succeeded, is not logged in again."""
    config = _both_providers_config()
    cloud = CloudCli(config)
    with (
        patch.object(
            AzureProvider,
            "login",
            new_callable=AsyncMock,
            side_effect=[LoginError({"Azure": "az: transient"}), None],
        ) as az,
        patch.object(GcpProvider, "login", new_callable=AsyncMock) as gcloud,
        patch("src.cloud_cli._cli.asyncio.sleep", new_callable=AsyncMock) as sleep,
    ):
        await cloud.ensure_login()
    assert az.await_count == 2
    assert gcloud.await_count == 1
    sleep.assert_awaited_once_with(config.cloud_login_retry_delay_sec)
    assert cloud._last_login > 0.0


@pytest.mark.asyncio
async def test_relogin_gives_up_after_configured_retries_with_backoff() -> None:
    cloud = CloudCli(
        _config(**_AZURE, cloud_login_retries=2, cloud_login_retry_delay_sec=1.5)
    )
    with (
        patch.object(
            AzureProvider,
            "login",
            new_callable=AsyncMock,
            side_effect=LoginError({"Azure": "az: still down"}),
        ) as az,
        patch("src.cloud_cli._cli.asyncio.sleep", new_callable=AsyncMock) as sleep,
        pytest.raises(
            LoginError, match="Cloud login failed for: Azure: az: still down"
        ),
    ):
        await cloud.ensure_login()
    assert az.await_count == 3  # initial + 2 retries
    assert [c.args[0] for c in sleep.await_args_list] == [1.5, 3.0]
    assert cloud._last_login == 0.0  # next job will try again


@pytest.mark.asyncio
async def test_startup_login_does_not_retry() -> None:
    """Startup is fail-fast: a broken credential must surface at once."""
    cloud = CloudCli(_both_providers_config())
    with (
        patch.object(
            AzureProvider,
            "login",
            new_callable=AsyncMock,
            side_effect=LoginError({"Azure": "az: bad secret"}),
        ) as az,
        patch.object(GcpProvider, "login", new_callable=AsyncMock),
        patch("src.cloud_cli._cli.asyncio.sleep", new_callable=AsyncMock) as sleep,
        pytest.raises(LoginError, match="Cloud login failed"),
    ):
        await cloud.login(retries=0)
    assert az.await_count == 1
    sleep.assert_not_awaited()


# ---------------------------------------------------------------------------
# CloudCli — scope_env
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scope_env_raises_credential_error_when_nothing_is_ready() -> None:
    """The error lists every provider's missing vars, so the job's 422
    tells the operator exactly what to set."""
    cloud = CloudCli(_config(azure_client_id="az-id"))
    with pytest.raises(CredentialError) as exc_info:
        await cloud.scope_env("sub-1")
    assert exc_info.value.missing == {
        "azure": ["ARM_CLIENT_SECRET", "ARM_TENANT_ID"],
        "gcp": [_GCP_MISSING],
        "aws": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
    }
    assert "No cloud provider credentials are complete" in str(exc_info.value)


@pytest.mark.asyncio
async def test_scope_env_injects_scope_for_every_ready_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEBULA_TEST_PASSTHROUGH", "1")
    cloud = CloudCli(_both_providers_config())
    env = await cloud.scope_env("scope-1")
    assert env["ARM_SUBSCRIPTION_ID"] == "scope-1"
    assert env["GOOGLE_PROJECT"] == "scope-1"
    assert env["NEBULA_TEST_PASSTHROUGH"] == "1"  # process env is inherited


@pytest.mark.asyncio
async def test_scope_env_only_injects_ready_providers() -> None:
    env = await CloudCli(_config(**_AZURE)).scope_env("sub-1")
    assert env["ARM_SUBSCRIPTION_ID"] == "sub-1"
    assert "GOOGLE_PROJECT" not in env


@pytest.mark.asyncio
async def test_scope_env_merges_assume_role_output() -> None:
    cloud = CloudCli(_config(**_AWS, aws_terraform_role_name="role/nebula"))
    with patch.object(
        AwsProvider, "_assume_role", new_callable=AsyncMock, return_value=_STS_CREDS
    ) as assume:
        env = await cloud.scope_env("123456789012")
    assume.assert_awaited_once_with("123456789012")
    assert env["AWS_SESSION_TOKEN"] == "TOKEN"
    assert env["AWS_ACCESS_KEY_ID"] == "AKID"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("AWS AssumeRole failed for arn:...: AccessDenied"),
        FileNotFoundError("aws"),  # CLI not installed
    ],
    ids=["sts-denied", "cli-missing"],
)
async def test_scope_env_propagates_assume_role_failure_when_aws_is_sole_provider(
    failure: Exception,
) -> None:
    """With AWS as the only ready provider there is no other cloud the
    scope could belong to, so a failed AssumeRole is a real auth problem.
    Swallowing it would run the engine with the service's static keys,
    i.e. against whatever account those keys belong to."""
    cloud = CloudCli(_config(**_AWS, aws_terraform_role_name="role/nebula"))
    with (
        patch.object(
            AwsProvider, "_assume_role", new_callable=AsyncMock, side_effect=failure
        ) as assume,
        pytest.raises(type(failure)),
    ):
        await cloud.scope_env("123456789012")
    assume.assert_awaited_once_with("123456789012")


# ---------------------------------------------------------------------------
# CloudCli — state_resource_ids
# ---------------------------------------------------------------------------


_STATE_DOC = {
    "version": 4,
    "resources": [
        {
            "mode": "managed",
            "type": "azurerm_resource_group",
            "instances": [
                {"attributes": {"id": "/subscriptions/s/resourceGroups/rg1"}},
                {"attributes": {"id": "/subscriptions/s/resourceGroups/rg2"}},
            ],
        },
        {
            "mode": "data",
            "type": "azurerm_client_config",
            "instances": [{"attributes": {"id": "data-id-ignored"}}],
        },
    ],
}


@pytest.mark.asyncio
async def test_state_resource_ids_returns_json_id_list(tmp_path: Path) -> None:
    pulled = _ok(json.dumps(_STATE_DOC))
    env = {"ARM_SUBSCRIPTION_ID": "sub-1"}
    with patch(
        "src.engine.state_pull", new_callable=AsyncMock, return_value=pulled
    ) as pull:
        result = await CloudCli(_config()).state_resource_ids("sh", tmp_path, env)
    pull.assert_awaited_once_with("sh", tmp_path, env=env)
    assert result == CommandResult(
        ok=True,
        stdout=json.dumps(
            [
                "/subscriptions/s/resourceGroups/rg1",
                "/subscriptions/s/resourceGroups/rg2",
            ]
        ),
        stderr="",
        exit_code=0,
    )


@pytest.mark.asyncio
async def test_state_resource_ids_passes_pull_failure_through(tmp_path: Path) -> None:
    """A failed ``state pull`` carries the command's exit code and stderr;
    stdout is empty rather than partial state."""
    pulled = CommandResult(
        ok=False, stdout="partial", stderr="Error: no state", exit_code=1
    )
    with patch("src.engine.state_pull", new_callable=AsyncMock, return_value=pulled):
        result = await CloudCli(_config()).state_resource_ids("sh", tmp_path, {})
    assert result == CommandResult(
        ok=False, stdout="", stderr="Error: no state", exit_code=1
    )


# ---------------------------------------------------------------------------
# CloudCli — scope_resource_ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scope_resource_ids_delegates_to_named_provider() -> None:
    listed = _ok('["id-1", "id-2"]')
    with (
        patch.object(
            AzureProvider,
            "list_resource_ids",
            new_callable=AsyncMock,
            return_value=listed,
        ) as azure_list,
        patch.object(
            GcpProvider, "list_resource_ids", new_callable=AsyncMock
        ) as gcp_list,
        patch.object(
            AwsProvider, "list_resource_ids", new_callable=AsyncMock
        ) as aws_list,
    ):
        result = await CloudCli(_config()).scope_resource_ids("azure", "sub-1")
    assert result is listed
    azure_list.assert_awaited_once_with("sub-1")
    gcp_list.assert_not_awaited()
    aws_list.assert_not_awaited()


@pytest.mark.asyncio
async def test_scope_resource_ids_unknown_provider_is_exit_code_2() -> None:
    with (
        patch.object(AzureProvider, "list_resource_ids", new_callable=AsyncMock) as az,
        patch.object(GcpProvider, "list_resource_ids", new_callable=AsyncMock) as gcp,
        patch.object(AwsProvider, "list_resource_ids", new_callable=AsyncMock) as aws,
    ):
        result = await CloudCli(_config()).scope_resource_ids("oci", "tenancy-1")
    assert result == CommandResult(
        ok=False,
        stdout="",
        stderr="Unsupported terraform_provider: 'oci'",
        exit_code=2,
    )
    for mock in (az, gcp, aws):
        mock.assert_not_awaited()
