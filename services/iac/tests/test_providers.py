# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for cloud provider detection from scope_id."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.providers import detect_provider_from_scope
from src.terraform import CommandResult


def test_azure_subscription_uuid() -> None:
    assert detect_provider_from_scope("a1b2c3d4-e5f6-7890-abcd-ef1234567890") == "azurerm"


def test_azure_subscription_uuid_uppercase() -> None:
    assert detect_provider_from_scope("A1B2C3D4-E5F6-7890-ABCD-EF1234567890") == "azurerm"


def test_aws_account_12_digits() -> None:
    assert detect_provider_from_scope("123456789012") == "aws"


def test_gcp_project_id() -> None:
    assert detect_provider_from_scope("my-gcp-project-123") == "google"


def test_gcp_project_numeric_name() -> None:
    # GCP numeric project IDs are typically longer than 12 digits
    assert detect_provider_from_scope("1234567890123") == "google"


def test_gcp_project_short_string() -> None:
    assert detect_provider_from_scope("my-project") == "google"


@pytest.mark.asyncio
async def test_azure_list_resource_ids_calls_az_cli() -> None:
    from src.azure import list_resource_ids

    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (
        json.dumps([
            "/subscriptions/sub-1/resourceGroups/rg-main",
            "/subscriptions/sub-1/resourceGroups/rg-main/providers/Microsoft.Compute/virtualMachines/vm-1",
        ]).encode(),
        b"",
    )
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        result = await list_resource_ids("sub-1")

    mock_exec.assert_awaited_once()
    call_args = mock_exec.call_args[0]
    assert call_args[0] == "az"
    assert "resource" in call_args
    assert "list" in call_args
    assert result.exit_code == 0
    ids = json.loads(result.stdout)
    assert len(ids) == 2


@pytest.mark.asyncio
async def test_azure_list_resource_ids_passes_through_failure() -> None:
    from src.azure import list_resource_ids

    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"", b"ERROR: not logged in")
    mock_proc.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await list_resource_ids("sub-1")

    assert result.exit_code == 1
    assert "not logged in" in result.stderr


@pytest.mark.asyncio
async def test_scope_resource_ids_dispatches_to_azure(tmp_path: Path) -> None:
    from src.providers import scope_resource_ids

    azure_result = CommandResult(
        ok=True,
        stdout=json.dumps(["/subscriptions/sub-1/resourceGroups/rg-main"]),
        stderr="",
        exit_code=0,
    )
    with patch("src.providers.azure.list_resource_ids", new_callable=AsyncMock, return_value=azure_result):
        # UUID scope_id → detected as Azure
        result = await scope_resource_ids(tmp_path, "a1b2c3d4-e5f6-7890-abcd-ef1234567890")

    assert result.exit_code == 0
    assert json.loads(result.stdout) == ["/subscriptions/sub-1/resourceGroups/rg-main"]


@pytest.mark.asyncio
async def test_aws_list_resource_ids_calls_aws_cli() -> None:
    from src.aws import list_resource_ids

    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (
        json.dumps({
            "ResourceTagMappingList": [
                {"ResourceARN": "arn:aws:ec2:us-east-1:123456789012:instance/i-abc123"},
                {"ResourceARN": "arn:aws:s3:::my-bucket"},
            ]
        }).encode(),
        b"",
    )
    mock_proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        result = await list_resource_ids("123456789012")

    mock_exec.assert_awaited_once()
    call_args = mock_exec.call_args[0]
    assert call_args[0] == "aws"
    assert "resourcegroupstaggingapi" in call_args
    assert "get-resources" in call_args
    assert result.exit_code == 0
    arns = json.loads(result.stdout)
    assert len(arns) == 2
    assert "arn:aws:ec2:us-east-1:123456789012:instance/i-abc123" in arns


@pytest.mark.asyncio
async def test_aws_list_resource_ids_passes_through_failure() -> None:
    from src.aws import list_resource_ids

    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"", b"Unable to locate credentials")
    mock_proc.returncode = 1

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await list_resource_ids("123456789012")

    assert result.exit_code == 1
    assert "Unable to locate credentials" in result.stderr


@pytest.mark.asyncio
async def test_scope_resource_ids_dispatches_to_aws(tmp_path: Path) -> None:
    from src.providers import scope_resource_ids

    aws_result = CommandResult(
        ok=True,
        stdout=json.dumps(["arn:aws:s3:::my-bucket"]),
        stderr="",
        exit_code=0,
    )
    with patch("src.providers.aws.list_resource_ids", new_callable=AsyncMock, return_value=aws_result):
        result = await scope_resource_ids(tmp_path, "123456789012")

    assert result.exit_code == 0
    assert json.loads(result.stdout) == ["arn:aws:s3:::my-bucket"]


@pytest.mark.asyncio
async def test_scope_resource_ids_dispatches_to_gcp(tmp_path: Path) -> None:
    from src.providers import scope_resource_ids

    gcp_result = CommandResult(
        ok=True,
        stdout=json.dumps(["//compute.googleapis.com/projects/my-proj/zones/us-central1-a/instances/vm-1"]),
        stderr="",
        exit_code=0,
    )
    with patch("src.providers.gcp.list_resource_ids", new_callable=AsyncMock, return_value=gcp_result):
        # non-UUID, non-12-digit scope_id → detected as GCP
        result = await scope_resource_ids(tmp_path, "my-gcp-project")

    assert result.exit_code == 0
    assert len(json.loads(result.stdout)) == 1
