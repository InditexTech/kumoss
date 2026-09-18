# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Storage config tests: how `terraform_state_bucket` opts state in and out."""

import unittest

import yaml

from src.shared.config.system_config import StorageConfig


def _from_yaml(document: str) -> StorageConfig:
    # Same path as SystemConfig.load(): parse the YAML, then validate.
    return StorageConfig.model_validate(yaml.safe_load(document) or {})


class TestTerraformStateBucket(unittest.TestCase):
    """The three ways a config can spell "no state bucket" — two of which
    mean managed state is off, and one of which does not."""

    def test_blank_string_turns_managed_state_off(self):
        cfg = _from_yaml('terraform_state_bucket: ""')
        self.assertEqual(cfg.terraform_state_bucket, "")
        self.assertEqual(cfg.state_bucket, "")

    def test_key_without_a_value_turns_managed_state_off(self):
        # `terraform_state_bucket:` parses as None. It reads as "no bucket",
        # so it must not fail validation and stop the boot.
        cfg = _from_yaml("terraform_state_bucket:")
        self.assertEqual(cfg.terraform_state_bucket, "")
        self.assertEqual(cfg.state_bucket, "")

    def test_whitespace_only_turns_managed_state_off(self):
        cfg = _from_yaml('terraform_state_bucket: "   "')
        self.assertEqual(cfg.state_bucket, "")

    def test_absent_key_falls_back_to_the_default_and_turns_it_on(self):
        cfg = _from_yaml("{}")
        self.assertEqual(cfg.state_bucket, "nebula-terraform-state")

    def test_a_name_turns_managed_state_on(self):
        cfg = _from_yaml('terraform_state_bucket: "acme-nebula-tfstate"')
        self.assertEqual(cfg.state_bucket, "acme-nebula-tfstate")


if __name__ == "__main__":
    unittest.main()
