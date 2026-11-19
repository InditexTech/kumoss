# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic
"""The provider vocabulary is repeated at every boundary the core crosses.

Providers are Terraform provider type names everywhere. The core keeps the
sets it knows more about (``SCOPED_PROVIDERS``, ``DISCOVERABLE_PROVIDERS``)
and passes names to the generated clients by value, so a provider missing
from a contract or a stale client fails only at runtime.
"""

import re
import unittest
from pathlib import Path
from typing import Any

import yaml

from src.clients.authz.models.resource_properties import ResourceProperties
from src.clients.iac.models.scope_resource_ids_request_provider import (
    ScopeResourceIdsRequestProvider,
)
from src.clients.mapping.models.terraform_provider import (
    TerraformProvider as MappingTerraformProvider,
)
from src.shared.constants import (
    DISCOVERABLE_PROVIDERS,
    LEGACY_PROVIDER_NAMES,
    SCOPED_PROVIDERS,
)


CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts" / "openapi"

_OLD_NAMES = {"azure", "gcp", "vmware"}


def _contract(service: str) -> dict[str, Any]:
    return yaml.safe_load((CONTRACTS_DIR / f"{service}.v1.yaml").read_text())


def _section(markdown: str, heading: str) -> str:
    """The body of the ``## heading`` section of a markdown text."""
    match = re.search(
        rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", markdown, re.M | re.S
    )
    assert match, f"no '## {heading}' section"
    return match.group(1)


class TestIacVocabulary(unittest.TestCase):
    def setUp(self):
        self.spec = _contract("iac")

    def test_discoverable_providers_match_the_scope_listing_enum(self):
        schema = self.spec["components"]["schemas"]["ScopeResourceIdsRequest"]
        self.assertEqual(
            set(schema["properties"]["provider"]["enum"]), DISCOVERABLE_PROVIDERS
        )
        self.assertEqual(
            {p.value for p in ScopeResourceIdsRequestProvider}, DISCOVERABLE_PROVIDERS
        )

    def test_scoped_providers_match_the_scope_injection_table(self):
        section = _section(self.spec["info"]["description"], "Scope injection")
        # First-column cells naming a provider (the endpoint table's cells
        # are paths, and `provider` is the header).
        injected = set(
            re.findall(r"^\|\s*`([a-z0-9][a-z0-9_-]*)`\s*\|", section, re.M)
        ) - {"provider"}
        self.assertEqual(injected, SCOPED_PROVIDERS)

    def test_every_discoverable_provider_is_scoped(self):
        self.assertLessEqual(DISCOVERABLE_PROVIDERS, SCOPED_PROVIDERS)

    def test_provider_scopes_take_any_provider_type_name(self):
        schema = self.spec["components"]["schemas"]["ProviderScope"]
        provider = schema["properties"]["provider"]
        self.assertEqual(provider["type"], "string")
        self.assertNotIn("enum", provider)
        self.assertNotIn("TerraformProvider", self.spec["components"]["schemas"])


class TestMappingVocabulary(unittest.TestCase):
    def test_contract_and_client_agree_on_terraform_names(self):
        contract = set(
            _contract("mapping")["components"]["schemas"]["TerraformProvider"]["enum"]
        )
        client = {p.value for p in MappingTerraformProvider}
        self.assertEqual(client, contract)
        self.assertLessEqual({"azurerm", "google", "vsphere"}, contract)
        self.assertFalse(contract & _OLD_NAMES)

    def test_api_literal_matches_the_mapping_client(self):
        from typing import get_args

        from src.api.dtos import MappingProvider

        self.assertEqual(
            set(get_args(MappingProvider)), {p.value for p in MappingTerraformProvider}
        )


class TestAuthzVocabulary(unittest.TestCase):
    def test_resource_provider_is_a_plain_string(self):
        props = _contract("authz")["components"]["schemas"]["ResourceProperties"]
        provider = props["properties"]["provider"]
        self.assertEqual(provider["type"], "string")
        self.assertNotIn("enum", provider)
        self.assertNotIn("$ref", provider)
        # The generated client carries it as a string too.
        resource = ResourceProperties(repo_uri="https://x/y", provider="vsphere")
        self.assertEqual(resource.to_dict()["provider"], "vsphere")


class TestLegacyNames(unittest.TestCase):
    def test_legacy_names_map_to_terraform_names(self):
        self.assertEqual(set(LEGACY_PROVIDER_NAMES), _OLD_NAMES)
        self.assertEqual(
            set(LEGACY_PROVIDER_NAMES.values()), {"azurerm", "google", "vsphere"}
        )


if __name__ == "__main__":
    unittest.main()
