# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for object storage adapter selection.

Adapter construction is IO-free and cached per (provider, bucket), so
these run without a store: they cover the Terraform state bucket being
the same store as the artifacts bucket under a different name, and the
unset setting that turns managed state off.
"""

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


if __name__ == "__main__":
    unittest.main()
