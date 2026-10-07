# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""The Terraform filenames the core writes are bare, safe filenames.

The backend override must also keep the `_override.tf` suffix: only then
does Terraform merge it over the configuration and the injected gitignore
keep it, with its credentials, out of the repository.
"""

import unittest

from pydantic import ValidationError

from src.shared.config.system_config import PathsConfig, StorageConfig

UNSAFE = ["", "../x", "a/b", "a b", "x" * 129]


class TestBackendOverrideFilename(unittest.TestCase):
    def test_default_is_an_override(self):
        self.assertEqual(PathsConfig().backend_override_filename, "backend_override.tf")

    def test_other_override_names_are_accepted(self):
        cfg = PathsConfig(backend_override_filename="kumoss_override.tf")
        self.assertEqual(cfg.backend_override_filename, "kumoss_override.tf")

    def test_names_terraform_would_not_merge_are_rejected(self):
        for name in [
            "backend.tf",
            "override.tf",
            "_override.tf.json",
            "a_override.tf/",
        ]:
            with self.subTest(name=name), self.assertRaises(ValidationError):
                _ = PathsConfig(backend_override_filename=name)

    def test_unsafe_names_are_rejected(self):
        for name in UNSAFE:
            with self.subTest(name=name), self.assertRaises(ValidationError):
                _ = PathsConfig(backend_override_filename=f"{name}_override.tf")


class TestTerraformStateFilename(unittest.TestCase):
    def test_default(self):
        self.assertEqual(StorageConfig().terraform_state_filename, "terraform.tfstate")

    def test_unsafe_names_are_rejected(self):
        for name in UNSAFE:
            with self.subTest(name=name), self.assertRaises(ValidationError):
                _ = StorageConfig(terraform_state_filename=name)


if __name__ == "__main__":
    unittest.main()
