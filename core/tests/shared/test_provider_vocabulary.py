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

import attrs
import yaml

from src.clients.authz.models.access_evaluation_request import (
    AccessEvaluationRequest,
)
from src.clients.authz.models.resource_properties import ResourceProperties
from src.clients.iac.models.scope_resource_ids_request_provider import (
    ScopeResourceIdsRequestProvider,
)
from src.clients.mapping.models.resolve_request import ResolveRequest
from src.clients.mapping.models.resolve_response import ResolveResponse
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
    def test_the_service_takes_no_provider_vocabulary(self):
        # Contract 2.0.0 resolves an identifier to a repository only:
        # providers come from the root module, scopes from its manifest.
        schemas = _contract("mapping")["components"]["schemas"]
        self.assertNotIn("TerraformProvider", schemas)
        self.assertEqual(set(schemas["ResolveRequest"]["properties"]), {"identifier"})
        self.assertEqual(
            set(schemas["ResolveResponse"]["properties"]), {"repo_url", "identifier"}
        )

    def test_the_client_carries_no_provider_or_scope(self):
        self.assertEqual(ResolveRequest(identifier="x").to_dict(), {"identifier": "x"})
        response = ResolveResponse(repo_url="https://x/y", identifier="x")
        self.assertEqual(set(response.to_dict()), {"repo_url", "identifier"})


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

    def test_request_envelope_matches_the_contract(self):
        # The contract dropped the request `context`; a stale client
        # would still let the core send it into an `additionalProperties:
        # false` envelope.
        schemas = _contract("authz")["components"]["schemas"]
        self.assertEqual(
            set(schemas["AccessEvaluationRequest"]["properties"]),
            {"subject", "action", "resource"},
        )
        self.assertEqual(
            set(attrs.fields_dict(AccessEvaluationRequest)),
            {"subject", "action", "resource"},
        )


if __name__ == "__main__":
    unittest.main()
