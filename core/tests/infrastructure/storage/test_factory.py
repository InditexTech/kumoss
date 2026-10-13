# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for object storage adapter selection.

Adapter construction is IO-free and cached per (provider, bucket), so
these run without a store: they cover the Terraform state bucket being
the same store as the artifacts bucket under a different name, and the
unset setting that turns managed state off.
"""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.infrastructure.storage import factory
from src.shared.config.system_config import StorageConfig
from src.shared.constants import ObjectStorageProvider


class TestTerraformStateStorage(unittest.TestCase):
    def _use(self, **overrides) -> StorageConfig:
        config = StorageConfig(
            **{
                "provider": ObjectStorageProvider.RUSTFS,
                "endpoint_url": "http://object-storage:9000",
                **overrides,
            }
        )
        patcher = patch.object(
            factory, "system_config", SimpleNamespace(storage=config)
        )
        _ = patcher.start()
        self.addCleanup(patcher.stop)
        return config

    def test_unset_state_bucket_turns_managed_state_off(self):
        for raw in ("", "   "):
            with self.subTest(terraform_state_bucket=raw):
                _ = self._use(terraform_state_bucket=raw, bucket="artifacts-off")
                self.assertIsNone(factory.terraform_state_storage())

    def test_the_state_store_is_the_artifacts_store_on_another_bucket(self):
        """One configured store holds both, reached with the same
        credentials, so the adapters differ only in the bucket."""
        config = self._use(bucket="artifacts-a", terraform_state_bucket="state-a")

        state = factory.terraform_state_storage()

        self.assertIs(state, factory._rustfs(config.state_bucket))
        self.assertIsNot(state, factory.default_object_storage())


class TestMetadataHeaderPrefix(unittest.TestCase):
    """Every provider must answer, not just the ones wired today.

    The SPA reads artifact metadata off pre-signed URLs and asks for the
    prefix this returns, so a new adapter that inherits a blank one would
    silently break the artifact viewer rather than fail at boot.
    """

    # STORAGE_ACCOUNT derives the account name from the endpoint host, so
    # the two families need different URLs to construct at all.
    ENDPOINTS = {
        ObjectStorageProvider.STORAGE_ACCOUNT: ("https://kumoss.blob.core.windows.net"),
    }

    def test_every_provider_answers_a_usable_prefix(self):
        # StorageConfig fail-fast validates that each provider's secret env
        # var is present; the values are never used, nothing is dialled.
        env = {
            "RUSTFS_ACCESS_KEY": "ak",
            "RUSTFS_SECRET_KEY": "sk",
            "STORAGE_ACCOUNT_KEY": "a2V5",
        }
        for provider in ObjectStorageProvider:
            with self.subTest(provider=provider), patch.dict(os.environ, env):
                config = StorageConfig(
                    provider=provider,
                    endpoint_url=self.ENDPOINTS.get(
                        provider, "http://object-storage:9000"
                    ),
                    bucket=f"prefix-probe-{provider.name}".lower(),
                )
                with patch.object(
                    factory, "system_config", SimpleNamespace(storage=config)
                ):
                    prefix = factory.default_object_storage().metadata_header_prefix
                self.assertTrue(prefix.endswith("-"), prefix)
                self.assertTrue(prefix.startswith("x-"), prefix)

    def test_the_two_s3_providers_share_the_amazon_prefix(self):
        """RUSTFS and S3 are one adapter — an enum-keyed table would let
        the next S3-compatible provider get the adapter but not the
        prefix."""
        self.assertEqual(
            factory._rustfs("a").metadata_header_prefix,
            factory._s3("b").metadata_header_prefix,
        )


if __name__ == "__main__":
    unittest.main()
