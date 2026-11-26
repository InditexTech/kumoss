# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""POST /v1/manifest/probe: request validation and the response shape."""

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from src.api.dtos import ManifestProbeRequest, ManifestProbeResponse
from src.api.v1.manifest import probe_manifest
from src.domains.services.manifest_service import reconcile_manifest, resolve_manifest
from src.domains.value_objects import (
    ProviderRequirement,
    RootModuleRef,
    TerraformRequirements,
    VarFile,
    VariableAnswer,
    VariableSpec,
)
from src.infrastructure.exceptions import RepositoryUnreachable

REQ = TerraformRequirements(
    providers=(
        ProviderRequirement("aws", "hashicorp/aws", (">= 5.0",)),
        ProviderRequirement("random", "hashicorp/random"),
    ),
    variables=(
        VariableSpec("region", "map(string)", required=True, description="Where."),
        VariableSpec("pw", "string", required=True, sensitive=True),
    ),
    var_files=(
        VarFile("envs/dev.tfvars", False, frozenset({"region"})),
        VarFile("envs/pro.tfvars", False),
    ),
)
MODULE = RootModuleRef("https://github.com/o/r", ".", Path("/w"))


class TestProbeRequest(unittest.TestCase):
    def test_validates_like_the_session_endpoints(self):
        ok = ManifestProbeRequest.model_validate({"repo_uri": "https://github.com/o/r"})
        self.assertIsNone(ok.root_module_path)
        # Providers come from the module itself: the request names none.
        self.assertNotIn("terraform_provider", ManifestProbeRequest.model_fields)
        for bad in (
            {"repo_uri": "git@github.com:o/r"},
            {"repo_uri": "https://u:t@github.com/o/r"},
            {"repo_uri": "https://github.com/o/r", "root_module_path": "../x"},
            {},
        ):
            with self.subTest(bad):
                with self.assertRaises(ValidationError):
                    _ = ManifestProbeRequest.model_validate(bad)


class TestProbeResponse(unittest.TestCase):
    def test_first_setup(self):
        body = ManifestProbeResponse.from_resolution(
            resolve_manifest(REQ, None, stored_secrets=())
        ).model_dump()
        self.assertEqual(body["status"], "not_found")
        self.assertTrue(body["needs_input"])
        self.assertEqual(
            body["missing_variables"],
            [
                {
                    "name": "region",
                    "type": "map(string)",
                    "description": "Where.",
                    "required": True,
                    "sensitive": False,
                },
                {
                    "name": "pw",
                    "type": "string",
                    "description": "",
                    "required": True,
                    "sensitive": True,
                },
            ],
        )
        self.assertEqual(
            body["selectable_var_files"],
            [
                {"path": "envs/dev.tfvars", "sets": ["region"]},
                {"path": "envs/pro.tfvars", "sets": []},
            ],
        )
        self.assertEqual(body["selected_var_files"], [])
        # Only scoped providers need a scope; random does not.
        self.assertEqual(
            body["missing_scopes"], [{"provider": "aws", "source": "hashicorp/aws"}]
        )

    def test_drift_reports_selection_and_provider_changes_but_no_values(self):
        manifest, secrets = reconcile_manifest(
            resolve_manifest(REQ, None, stored_secrets=()),
            {"region": VariableAnswer({"a": "b"}), "pw": VariableAnswer("s3cr3t")},
            ["envs/pro.tfvars"],
            {},
            {"aws": "123456789012"},
            module=MODULE,
        )
        bumped = TerraformRequirements(
            providers=(
                ProviderRequirement("aws", "hashicorp/aws", ("~> 6.0",)),
                ProviderRequirement("random", "hashicorp/random"),
            ),
            variables=REQ.variables,
            var_files=REQ.var_files,
        )
        response = ManifestProbeResponse.from_resolution(
            resolve_manifest(bumped, manifest, stored_secrets=secrets.keys())
        )
        body = response.model_dump()
        self.assertEqual(body["status"], "drifted")
        self.assertFalse(body["needs_input"])
        self.assertEqual(body["selected_var_files"], ["envs/pro.tfvars"])
        self.assertEqual(body["missing_scopes"], [])
        self.assertEqual(
            body["provider_changes"],
            [
                {
                    "name": "aws",
                    "before": "hashicorp/aws >= 5.0",
                    "after": "hashicorp/aws ~> 6.0",
                }
            ],
        )
        self.assertNotIn("s3cr3t", response.model_dump_json())
        self.assertNotIn("westeurope", response.model_dump_json())

    def test_selection_keeps_its_saved_order(self):
        manifest, secrets = reconcile_manifest(
            resolve_manifest(REQ, None, stored_secrets=()),
            {"region": VariableAnswer({"a": "b"}), "pw": VariableAnswer("s3cr3t")},
            ["envs/pro.tfvars", "envs/dev.tfvars"],
            {},
            {"aws": "123456789012"},
            module=MODULE,
        )
        body = ManifestProbeResponse.from_resolution(
            resolve_manifest(REQ, manifest, stored_secrets=secrets.keys())
        ).model_dump()
        self.assertEqual(
            body["selected_var_files"], ["envs/pro.tfvars", "envs/dev.tfvars"]
        )

    def test_lists_variables_only_a_picked_file_sets(self):
        # region comes only from the picked dev.tfvars; the secret is lost,
        # so the form opens and must still be able to ask for region if
        # the user unpicks that file.
        manifest, _ = reconcile_manifest(
            resolve_manifest(REQ, None, stored_secrets=()),
            {"pw": VariableAnswer("s3cr3t")},
            ["envs/dev.tfvars"],
            {},
            {"aws": "123456789012"},
            module=MODULE,
        )
        resolution = resolve_manifest(REQ, manifest, stored_secrets=())
        self.assertEqual([v.name for v in resolution.missing_variables], ["pw"])
        body = ManifestProbeResponse.from_resolution(resolution).model_dump()
        self.assertTrue(body["needs_input"])
        self.assertEqual(
            [v["name"] for v in body["missing_variables"]], ["region", "pw"]
        )


class TestProbeEndpoint(unittest.IsolatedAsyncioTestCase):
    async def test_maps_domain_errors_to_http(self):
        service = MagicMock()
        service.probe = AsyncMock(side_effect=RepositoryUnreachable(400))
        with patch(
            "src.api.v1.manifest.ApplicationFactory.get_manifest_probe_service",
            return_value=service,
        ):
            with self.assertRaises(HTTPException) as ctx:
                _ = await probe_manifest(
                    ManifestProbeRequest(repo_uri="https://github.com/o/r")
                )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_returns_the_resolution(self):
        service = MagicMock()
        service.probe = AsyncMock(
            return_value=resolve_manifest(REQ, None, stored_secrets=())
        )
        with patch(
            "src.api.v1.manifest.ApplicationFactory.get_manifest_probe_service",
            return_value=service,
        ):
            response = await probe_manifest(
                ManifestProbeRequest(
                    repo_uri="https://github.com/o/r",
                    root_module_path="infra",
                )
            )
        service.probe.assert_awaited_once_with(
            repo_uri="https://github.com/o/r",
            root_module_path="infra",
        )
        self.assertTrue(response.needs_input)
        self.assertEqual(
            [m.model_dump() for m in response.missing_scopes],
            [{"provider": "aws", "source": "hashicorp/aws"}],
        )

    async def test_missing_scope_source_is_the_registry_address(self):
        req = TerraformRequirements(
            providers=(
                ProviderRequirement(
                    "azurerm", "registry.terraform.io/hashicorp/azurerm"
                ),
                ProviderRequirement("google", "hashicorp/google"),
            ),
        )
        body = ManifestProbeResponse.from_resolution(
            resolve_manifest(req, None, stored_secrets=())
        ).model_dump()
        self.assertTrue(body["needs_input"])
        self.assertEqual(
            body["missing_scopes"],
            [
                {
                    "provider": "azurerm",
                    "source": "registry.terraform.io/hashicorp/azurerm",
                },
                {"provider": "google", "source": "hashicorp/google"},
            ],
        )
