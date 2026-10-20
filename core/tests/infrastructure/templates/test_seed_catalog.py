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

    def test_forbidden_actions_defer_deletions_to_the_compliance_check(self):
        # critical_deletion rejects every standalone delete, even a requested
        # one; no seed may suggest a request can authorize it.
        for provider in TerraformProvider:
            with self.subTest(provider=provider.value):
                body = " ".join(
                    _body(provider.value, "guidelines", "forbidden_actions").split()
                )
                self.assertIn(
                    "Standalone deletions are always rejected by the compliance"
                    " check, even when requested",
                    body,
                )
                self.assertNotIn("override request", body)

    def test_existing_provider_pins_are_kept(self):
        # The seeds pin newer majors than earlier releases did, and `init`
        # runs without -upgrade: rewriting an existing workspace's pin
        # breaks against its lock file.
        body = " ".join(_body("general", "guidelines", "terraform").split())
        self.assertIn("apply to new workspaces only", body)
        self.assertIn("never change that constraint", body)
        self.assertIn("valid for the pinned version", body)

    def test_aws_keeps_an_existing_provider_region(self):
        # Dropping `region` from an existing provider block moves every
        # resource to the engine's AWS_REGION: the plan re-creates them.
        body = " ".join(_body("aws", "guidelines", "resource_creation").split())
        self.assertIn(
            "If an existing provider block already sets `region` (a literal or"
            " a variable), never remove or change it",
            body,
        )

    def test_resource_creation_forbids_backend_blocks(self):
        # State is configured outside the generated code (a Kumoss override
        # or the repository's own backend); a generated backend clashes.
        for provider in TerraformProvider:
            with self.subTest(provider=provider.value):
                body = _body(provider.value, "guidelines", "resource_creation")
                self.assertIn("backend", body)


class TestStandardTags(unittest.TestCase):
    """One tag convention for every scope: a literal `standard_tags` local
    defined once per workspace, never values the engine cannot supply."""

    def test_general_guidelines_define_the_standard_tags_file(self):
        body = _body("general", "guidelines", "terraform")
        self.assertIn("standard_tags.tf", body)
        for key in ("environment", "owner", "managed_by"):
            self.assertIn(key, body)

    def test_every_scope_attaches_the_standard_tags_local(self):
        for provider in TerraformProvider:
            with self.subTest(provider=provider.value):
                body = _body(provider.value, "guidelines", "resource_creation")
                self.assertIn("local.standard_tags", body)

    def test_no_seed_uses_another_tags_source(self):
        # Per-cloud local names or variables with no value at plan time.
        for path in sorted(SEED_DIR.rglob("*.yaml")):
            with self.subTest(seed=str(path.relative_to(SEED_DIR))):
                body = yaml.safe_load(path.read_text(encoding="utf-8"))["body"]
                for stale in (
                    "local.common_tags",
                    "local.tags",
                    "var.owner",
                    "var.environment",
                ):
                    self.assertNotIn(stale, body)

    def test_aws_never_retags_existing_resources_through_default_tags(self):
        # default_tags reach every resource the provider manages, so adding
        # them to an existing provider block retags the whole workspace.
        body = " ".join(_body("aws", "guidelines", "resource_creation").split())
        self.assertIn(
            "already has an `aws` provider block without `default_tags`, never"
            " add `default_tags` to it",
            body,
        )
        self.assertIn("merge(local.standard_tags,", body)


class TestVmwareSeeds(unittest.TestCase):
    def test_resource_creation_pins_the_vsphere_provider(self):
        body = _body("vmware", "guidelines", "resource_creation")
        self.assertIn('source  = "vmware/vsphere"', body)
        self.assertIn('version = "~> 2.10"', body)
        # Credentials and TLS settings come from the engine's environment;
        # an explicit argument would override VSPHERE_ALLOW_UNVERIFIED_SSL.
        self.assertIn("VSPHERE_SERVER", body)
        self.assertNotIn("allow_unverified_ssl = false", body)

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
        self.assertIn('version = "~> 8.0"', body)
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


class TestEngineInjectedVariables(unittest.TestCase):
    """The iac sidecar injects scope_id as TF_VAR_<name> for OCI and AWS
    (services/iac/src/engine.py ``_SCOPE_ENV_VARS``). The variable name is a
    contract between that map and these prompts, held only by this test:
    a seed naming another variable gets no value and the plan fails, or the
    command silently runs outside the requested scope."""

    def test_oci_resource_creation_declares_the_injected_compartment(self):
        body = _body("oci", "guidelines", "resource_creation")
        self.assertIn('variable "compartment_ocid"', body)

    def test_oci_seeds_name_no_other_compartment_variable(self):
        # tenancy_ocid is the root compartment, set by the deployment.
        for path in sorted((SEED_DIR / "oci").rglob("*.yaml")):
            with self.subTest(seed=path.name):
                body = yaml.safe_load(path.read_text(encoding="utf-8"))["body"]
                for var in re.findall(r"var\.(\w*(?:compartment|tenancy)\w*)", body):
                    self.assertIn(var, {"compartment_ocid", "tenancy_ocid"})

    def test_aws_provider_is_pinned_to_the_injected_account(self):
        body = _body("aws", "guidelines", "resource_creation")
        self.assertIn('variable "aws_account_id"', body)
        self.assertIn("allowed_account_ids = [var.aws_account_id]", body)
        self.assertIn("TF_VAR_aws_account_id", body)


class TestSingleSourceConventions(unittest.TestCase):
    """resource_creation is injected into every request, resource templates
    only when selected: a cross-cutting rule lives once in the former, and a
    per-resource fact once in the latter."""

    # Resource templates allowed to name the standard tags because they
    # are an exception the cloud's rule does not reach.
    _STANDARD_TAG_EXCEPTIONS = {
        ("aws", "auto_scaling_group"),  # default_tags skip ASGs
        ("aws", "launch_template"),  # ...and the instances they launch
        ("oci", "compute_instance"),  # tags inside an HCL example
        ("vmware", "tag"),  # creates the tags the rule looks up
    }

    def test_resource_templates_do_not_restate_the_tag_rule(self):
        for provider in TerraformProvider:
            for name in sorted(_names(provider.value, "resources")):
                if (provider.value, name) in self._STANDARD_TAG_EXCEPTIONS:
                    continue
                with self.subTest(seed=f"{provider.value}/{name}"):
                    body = _body(provider.value, "resources", name)
                    self.assertNotIn("local.standard_tags", body)

    def test_replacement_arguments_live_in_the_resource_templates(self):
        for provider in TerraformProvider:
            with self.subTest(provider=provider.value):
                body = " ".join(
                    _body(provider.value, "guidelines", "resource_creation").split()
                )
                self.assertRegex(
                    body, r"Each resource template lists the [\w ]+ that force"
                    r" its replacement"
                )
                self.assertNotRegex(body, r"arguments that force replacement:")


if __name__ == "__main__":
    unittest.main()
