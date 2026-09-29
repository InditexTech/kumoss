# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Terraform state backend the core writes.

Kumoss's own object store holds the state, so the override rendered
into each workspace follows ``storage.provider``: the ``s3`` backend
against a custom endpoint for RUSTFS, plain ``s3`` for AWS, ``azurerm``
for a storage account. These cover the three renderings, the static
credentials being embedded only when the configuration carries them,
the ``terraform_state_bucket``-empty case that leaves the workspace's
own backend alone, and what ``apply`` writes.
"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.infrastructure.terraform.backend import (
    OVERRIDE_FILENAME,
    TerraformBackend,
)
from src.shared.config.system_config import StorageConfig
from src.shared.constants import ObjectStorageProvider


PROJECT_ID = "a" * 64
STATE_BUCKET = "kumoss-terraform-state"

_AK_ENV = "TEST_BACKEND_ACCESS_KEY"
_SK_ENV = "TEST_BACKEND_SECRET_KEY"
_ACCOUNT_KEY_ENV = "TEST_BACKEND_ACCOUNT_KEY"


def _s3_config(**overrides) -> StorageConfig:
    return StorageConfig(
        **{
            "provider": ObjectStorageProvider.S3,
            "terraform_state_bucket": STATE_BUCKET,
            "region": "eu-west-1",
            "access_key_env": _AK_ENV,
            "secret_key_env": _SK_ENV,
            **overrides,
        }
    )


def _rustfs_config(**overrides) -> StorageConfig:
    return StorageConfig(
        **{
            "provider": ObjectStorageProvider.RUSTFS,
            "terraform_state_bucket": STATE_BUCKET,
            "endpoint_url": "http://object-storage:9000",
            **overrides,
        }
    )


def _azure_config(**overrides) -> StorageConfig:
    # The account key is required at construction (the artifacts adapter
    # presigns with it), so it is always in the environment here; the
    # keyless rendering below drops it at render time instead.
    with patch.dict(os.environ, {_ACCOUNT_KEY_ENV: "azure-key"}):
        return StorageConfig(
            **{
                "provider": ObjectStorageProvider.STORAGE_ACCOUNT,
                "terraform_state_bucket": "tfstate",
                "endpoint_url": "https://kumossacct.blob.core.windows.net",
                "public_endpoint_url": "https://kumossacct.blob.core.windows.net",
                "account_key_env": _ACCOUNT_KEY_ENV,
                **overrides,
            }
        )


class TestStateKey(unittest.TestCase):
    def test_state_is_keyed_by_project(self):
        """Clone directories are per-call, so two runs of one project are
        brought together by the project digest instead."""
        backend = TerraformBackend(PROJECT_ID, _rustfs_config())
        self.assertEqual(backend.state_key, f"{PROJECT_ID}/terraform.tfstate")

    def test_the_filename_is_an_override(self):
        """The merge semantics this relies on come from the `_override`
        suffix; any other name would be a second backend block rather
        than a replacement."""
        self.assertTrue(OVERRIDE_FILENAME.endswith("_override.tf"))


class TestRustfsRendering(unittest.TestCase):
    def setUp(self):
        self.rendered = TerraformBackend(PROJECT_ID, _rustfs_config()).render() or ""

    def test_it_is_the_s3_backend_on_the_bundled_store(self):
        self.assertIn('backend "s3"', self.rendered)
        self.assertIn(f'bucket = "{STATE_BUCKET}"', self.rendered)
        self.assertIn(f'key    = "{PROJECT_ID}/terraform.tfstate"', self.rendered)
        self.assertIn('s3 = "http://object-storage:9000"', self.rendered)

    def test_the_aws_specific_preflight_is_skipped(self):
        """rustfs is not AWS: path-style addressing, no account or
        metadata lookups, and S3-native locking rather than DynamoDB."""
        for flag in (
            "use_path_style              = true",
            "skip_credentials_validation = true",
            "skip_region_validation      = true",
            "skip_requesting_account_id  = true",
            "skip_metadata_api_check     = true",
            "skip_s3_checksum            = true",
            "use_lockfile                = true",
        ):
            self.assertIn(flag, self.rendered)

    def test_the_bundled_credentials_are_embedded(self):
        self.assertIn('access_key = "rustfsadmin"', self.rendered)
        self.assertIn('secret_key = "rustfsadmin"', self.rendered)


class TestS3Rendering(unittest.TestCase):
    def _render(self, env: dict[str, str]) -> str:
        with patch.dict(os.environ, env, clear=False):
            for name in (_AK_ENV, _SK_ENV):
                if name not in env:
                    _ = os.environ.pop(name, None)
            return TerraformBackend(PROJECT_ID, _s3_config()).render() or ""

    def test_aws_gets_no_custom_endpoint(self):
        """boto3 and Terraform both build the regional endpoint
        themselves; overriding it would pin the state to one region's
        hostname."""
        rendered = self._render({_AK_ENV: "AKIA", _SK_ENV: "secret"})
        self.assertIn('backend "s3"', rendered)
        self.assertIn('region = "eu-west-1"', rendered)
        self.assertNotIn("endpoints", rendered)
        self.assertNotIn("skip_", rendered)
        self.assertIn("use_lockfile = true", rendered)

    def test_static_credentials_are_embedded_when_configured(self):
        rendered = self._render({_AK_ENV: "AKIA", _SK_ENV: "secret"})
        self.assertIn('access_key = "AKIA"', rendered)
        self.assertIn('secret_key = "secret"', rendered)

    def test_credentials_are_omitted_when_the_store_has_none(self):
        """A deployment on an instance profile or IRSA configures no
        keys; the backend then resolves them the way the AWS SDK does."""
        rendered = self._render({})
        self.assertIn('bucket = "kumoss-terraform-state"', rendered)
        self.assertNotIn("access_key", rendered)
        self.assertNotIn("secret_key", rendered)


class TestStorageAccountRendering(unittest.TestCase):
    def test_it_is_the_azurerm_backend_on_the_state_container(self):
        with patch.dict(os.environ, {_ACCOUNT_KEY_ENV: "azure-key"}):
            rendered = TerraformBackend(PROJECT_ID, _azure_config()).render() or ""
        self.assertIn('backend "azurerm"', rendered)
        self.assertIn('storage_account_name = "kumossacct"', rendered)
        self.assertIn('container_name       = "tfstate"', rendered)
        self.assertIn(
            f'key                  = "{PROJECT_ID}/terraform.tfstate"', rendered
        )
        self.assertIn('access_key           = "azure-key"', rendered)

    def test_entra_id_auth_replaces_a_missing_account_key(self):
        config = _azure_config()
        with patch.dict(os.environ, {}, clear=False):
            _ = os.environ.pop(_ACCOUNT_KEY_ENV, None)
            rendered = TerraformBackend(PROJECT_ID, config).render() or ""
        self.assertIn("use_azuread_auth     = true", rendered)
        self.assertNotIn("access_key", rendered)


class TestUnmanagedState(unittest.TestCase):
    def test_an_empty_bucket_renders_nothing(self):
        """Managed state off: every workspace keeps the backend its own
        configuration declares."""
        for raw in ("", "   "):
            with self.subTest(terraform_state_bucket=raw):
                config = _rustfs_config(terraform_state_bucket=raw)
                self.assertIsNone(TerraformBackend(PROJECT_ID, config).render())


class TestApply(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name)

    def test_it_writes_the_override_into_the_workspace(self):
        backend = TerraformBackend(PROJECT_ID, _rustfs_config())

        self.assertTrue(backend.apply(self.workspace))

        override = self.workspace / OVERRIDE_FILENAME
        self.assertEqual(override.read_text(encoding="utf-8"), backend.render())

    def test_it_rewrites_a_stale_override(self):
        """A pinned workspace re-inited for another project must not keep
        the previous project's state key."""
        other = "b" * 64
        config = _rustfs_config()
        _ = TerraformBackend(other, config).apply(self.workspace)
        _ = TerraformBackend(PROJECT_ID, config).apply(self.workspace)

        rendered = (self.workspace / OVERRIDE_FILENAME).read_text(encoding="utf-8")
        self.assertIn(PROJECT_ID, rendered)
        self.assertNotIn(other, rendered)

    def test_it_writes_nothing_when_state_is_unmanaged(self):
        config = _rustfs_config(terraform_state_bucket="")

        self.assertFalse(TerraformBackend(PROJECT_ID, config).apply(self.workspace))
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_an_unwritable_workspace_does_not_raise(self):
        """`init` reports a missing backend far more legibly than an
        exception from here would, so a failed write is only logged."""
        backend = TerraformBackend(PROJECT_ID, _rustfs_config())

        self.assertFalse(backend.apply(self.workspace / "does-not-exist"))


if __name__ == "__main__":
    unittest.main()
