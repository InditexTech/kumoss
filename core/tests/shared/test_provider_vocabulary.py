# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic
"""The provider vocabulary is repeated at every boundary the core crosses.

Providers are Terraform provider type names everywhere. The core keeps the
ones it knows more about (``SCOPE_BINDINGS``, ``DISCOVERABLE_PROVIDERS``)
and passes names to the generated clients by value, so a provider missing
from a contract or a stale client fails only at runtime.
"""

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
    SCOPE_BINDINGS,
    SCOPED_PROVIDERS,
)


CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts" / "openapi"

_OLD_NAMES = {"azure", "gcp", "vmware"}


def _contract(service: str) -> dict[str, Any]:
    return yaml.safe_load((CONTRACTS_DIR / f"{service}.v1.yaml").read_text())


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

    def test_scope_bindings_fit_the_request_fields(self):
        # The IaC service knows no providers: each scope reaches it as an
        # `env` or `vars` entry, so its name must be one those accept.
        schemas = self.spec["components"]["schemas"]
        patterns = {
            "env": schemas["Env"]["propertyNames"]["pattern"],
            "var": schemas["Vars"]["propertyNames"]["pattern"],
        }
        for provider, binding in SCOPE_BINDINGS.items():
            self.assertRegex(binding.name, patterns[binding.kind], provider)

    def test_every_discoverable_provider_is_scoped(self):
        self.assertLessEqual(DISCOVERABLE_PROVIDERS, SCOPED_PROVIDERS)

    def test_the_service_takes_no_provider_vocabulary(self):
        schemas = self.spec["components"]["schemas"]
        self.assertNotIn("ProviderScope", schemas)
        self.assertNotIn("TerraformProvider", schemas)


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


if __name__ == "__main__":
    unittest.main()
