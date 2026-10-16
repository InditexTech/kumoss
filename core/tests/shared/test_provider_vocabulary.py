# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic
"""The provider vocabulary is repeated at every boundary the core crosses.

The core converts its enum to the generated clients' by value, so a
provider missing from a contract or a stale client fails only at runtime.
"""

import unittest
from pathlib import Path

import yaml

from src.clients.iac.models.terraform_provider import (
    TerraformProvider as IacTerraformProvider,
)
from src.clients.mapping.models.terraform_provider import (
    TerraformProvider as MappingTerraformProvider,
)
from src.shared.constants import TerraformProvider


CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts" / "openapi"


def _contract_enum(service: str) -> set[str]:
    spec = yaml.safe_load((CONTRACTS_DIR / f"{service}.v1.yaml").read_text())
    return set(spec["components"]["schemas"]["TerraformProvider"]["enum"])


class TestProviderVocabulary(unittest.TestCase):
    def setUp(self):
        self.core = {p.value for p in TerraformProvider}

    def test_generated_clients_match_the_core(self):
        self.assertEqual({p.value for p in IacTerraformProvider}, self.core)
        self.assertEqual({p.value for p in MappingTerraformProvider}, self.core)

    def test_contracts_match_the_core(self):
        for service in ("iac", "mapping"):
            with self.subTest(service=service):
                self.assertEqual(_contract_enum(service), self.core)

    def test_vmware_is_supported(self):
        self.assertIn("vmware", self.core)


if __name__ == "__main__":
    unittest.main()
