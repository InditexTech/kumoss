# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic
"""Checks the shipped seed tree, not a synthetic one.

``test_seed_loader`` covers the loader's rules; this covers what the
repository actually ships: every provider has the guideline prompts the
template adapter fetches, and every resource template is reachable
through its ``resources_list``.
"""

import re
import unittest
from pathlib import Path

import yaml

from src.infrastructure.templates._seed_loader import SeedLoader
from src.shared.constants import TerraformProvider


SEED_DIR = Path(__file__).resolve().parents[3] / "prompts" / "seed"

# Fetched by TemplateAdapter for every provider scope.
REQUIRED_GUIDELINES = {
    "abbreviations",
    "drift_exceptions",
    "forbidden_actions",
    "networking",
    "permissions",
    "resource_creation",
    "resources_list",
}

# A top-level bullet naming a template, with or without backticks:
# "- `vcn` — Virtual Cloud Network" or "- namespace". YAML strips the
# block scalar's indentation, so bullets start the line.
_LISTED_NAME_RE = re.compile(r"^- `?([a-z0-9_]+)`?(?:\s|$)", re.MULTILINE)


def _body(scope: str, type_: str, name: str) -> str:
    path = SEED_DIR / scope / type_ / f"{name}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))["body"]


def _names(scope: str, type_: str) -> set[str]:
    return {p.stem for p in (SEED_DIR / scope / type_).glob("*.yaml")}


class TestSeedCatalog(unittest.TestCase):
    def test_shipped_seeds_load(self):
        entries = SeedLoader(SEED_DIR).load()
        self.assertTrue(entries)

    def test_every_provider_has_required_guidelines(self):
        for provider in TerraformProvider:
            with self.subTest(provider=provider.value):
                missing = REQUIRED_GUIDELINES - _names(provider.value, "guidelines")
                self.assertEqual(missing, set())

    def test_resources_list_matches_resource_templates(self):
        for provider in TerraformProvider:
            with self.subTest(provider=provider.value):
                listed = set(
                    _LISTED_NAME_RE.findall(
                        _body(provider.value, "guidelines", "resources_list")
                    )
                )
                self.assertEqual(listed, _names(provider.value, "resources"))


class TestVmwareSeeds(unittest.TestCase):
    def test_resource_creation_pins_the_vsphere_provider(self):
        body = _body("vmware", "guidelines", "resource_creation")
        self.assertIn('source  = "vmware/vsphere"', body)
        self.assertIn('version = "~> 2.10"', body)
        self.assertIn("allow_unverified_ssl = false", body)

    def test_no_resource_template_suggests_command_execution(self):
        # The general Terraform guidelines forbid provisioners and
        # null_resource; guest setup goes through customization instead.
        for name in _names("vmware", "resources"):
            with self.subTest(template=name):
                body = _body("vmware", "resources", name)
                for banned in ("null_resource", "local-exec", "remote-exec"):
                    self.assertNotIn(banned, body)

    def test_forbidden_actions_cover_host_and_identity_guardrails(self):
        body = _body("vmware", "guidelines", "forbidden_actions")
        for rule in (
            "allow_unverified_ssl = true",
            "Administrator",
            "promiscuous",
            "vsphere_host",
        ):
            self.assertIn(rule, body)


class TestGcpSeeds(unittest.TestCase):
    def test_resource_creation_leaves_the_project_to_the_engine(self):
        # The IaC sidecar injects the request's project as GOOGLE_PROJECT;
        # a provider-level project would override it.
        body = _body("gcp", "guidelines", "resource_creation")
        self.assertIn('source  = "hashicorp/google"', body)
        self.assertIn('version = "~> 7.0"', body)
        self.assertIn("GOOGLE_PROJECT", body)
        self.assertNotIn("project = var.", body)

    def test_no_resource_template_suggests_command_execution(self):
        for name in _names("gcp", "resources"):
            with self.subTest(template=name):
                body = _body("gcp", "resources", name)
                for banned in ("null_resource", "local-exec", "remote-exec"):
                    self.assertNotIn(banned, body)

    def test_compute_templates_cover_vm_hardening(self):
        for name in ("compute_instance", "instance_template"):
            with self.subTest(template=name):
                # Collapse the block scalar's line wrapping before matching prose.
                body = " ".join(_body("gcp", "resources", name).split())
                for rule in (
                    "access_config",
                    "enable-oslogin",
                    "shielded_instance_config",
                    "default service account",
                ):
                    self.assertIn(rule, body)

    def test_forbidden_actions_cover_identity_and_data_guardrails(self):
        body = " ".join(_body("gcp", "guidelines", "forbidden_actions").split())
        for rule in (
            "0.0.0.0/0",
            "google_service_account_key",
            "allUsers",
            "_iam_policy",
            "default service account",
            "deletion_protection = false",
        ):
            self.assertIn(rule, body)


if __name__ == "__main__":
    unittest.main()
