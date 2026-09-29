# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for TerraformImportService.

Cover the two derivations the service owns so its callers do not have to
repeat them: the unmanaged resource diff, withheld by the import exception
list, and the partition of an import round into the resources now tracked
in state and the ones Terraform rejected.
"""

import unittest
from pathlib import Path
from unittest.mock import AsyncMock

import yaml

from src.application.services.terraform_import_service import TerraformImportService
from src.domains.dto import (
    PromptTemplateDTO,
    TerraformDiscoveryDTO,
    TerraformImportResourceDTO,
)
from src.shared.constants import PromptsLibrary, TerraformProvider


def _discovery(resource_ids: list[str], feedback: str = "") -> TerraformDiscoveryDTO:
    return TerraformDiscoveryDTO(resource_ids=resource_ids, feedback=feedback)


def _exceptions(body: str) -> PromptTemplateDTO:
    return PromptTemplateDTO(type=PromptsLibrary.IMPORT_EXCEPTIONS, prompt=body)


def _exception_list(*ids: str) -> PromptTemplateDTO:
    return _exceptions("# Import Exception List\n\n" + "".join(f"- {i}\n" for i in ids))


def _import_result(ok: bool, feedback: str = "") -> TerraformImportResourceDTO:
    return TerraformImportResourceDTO(ok=ok, stdout="", feedback=feedback)


class TestTerraformImportService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.import_prv = AsyncMock()
        self.template_svc = AsyncMock()
        self.template_svc.render.return_value = _exception_list()
        self.service = TerraformImportService(
            import_provider=self.import_prv,
            template_service=self.template_svc,
        )

    # --- Discovery ---

    async def test_unmanaged_resources_are_the_sorted_scope_diff(self):
        self.import_prv.state_resource_ids.return_value = _discovery(["res-b"])
        self.import_prv.scope_resource_ids.return_value = _discovery(
            ["res-c", "res-a", "res-b"]
        )

        discovery = await self.service.get_unmanaged_resources(
            scope_id="scope-123",
            terraform_provider=TerraformProvider.AZURE,
        )

        self.assertEqual(discovery.resource_ids, ["res-a", "res-c"])
        self.assertEqual(discovery.feedback, "")

    async def test_failed_scope_query_reports_the_provider_diagnostics(self):
        # The three ways a round finds nothing to import stay apart: here
        # the query failed, so its stderr reaches the caller verbatim.
        self.import_prv.state_resource_ids.return_value = _discovery([])
        self.import_prv.scope_resource_ids.return_value = _discovery(
            [], "Error: invalid token"
        )

        discovery = await self.service.get_unmanaged_resources(
            scope_id="scope-123",
            terraform_provider=TerraformProvider.AZURE,
        )

        self.assertEqual(discovery.resource_ids, [])
        self.assertIn("could not be listed", discovery.feedback)
        self.assertIn("Error: invalid token", discovery.feedback)

    async def test_empty_scope_is_reported_apart_from_a_failed_query(self):
        self.import_prv.state_resource_ids.return_value = _discovery([])
        self.import_prv.scope_resource_ids.return_value = _discovery([])

        discovery = await self.service.get_unmanaged_resources(
            scope_id="scope-123",
            terraform_provider=TerraformProvider.AZURE,
        )

        self.assertEqual(discovery.resource_ids, [])
        self.assertIn("holds no importable resource", discovery.feedback)

    async def test_fully_managed_scope_is_reported_apart_from_an_empty_one(self):
        self.import_prv.state_resource_ids.return_value = _discovery(["res-a", "res-b"])
        self.import_prv.scope_resource_ids.return_value = _discovery(["res-a", "res-b"])

        discovery = await self.service.get_unmanaged_resources(
            scope_id="scope-123",
            terraform_provider=TerraformProvider.AZURE,
        )

        self.assertEqual(discovery.resource_ids, [])
        self.assertIn("already managed", discovery.feedback)

    async def test_azure_ids_compare_case_insensitively(self):
        # Resource Graph and the state need not agree on segment case; a
        # resource tracked as /resourceGroups/ is managed even when listed
        # as /resourcegroups/.
        self.import_prv.state_resource_ids.return_value = _discovery(
            ["/subscriptions/s/resourceGroups/rg-a"]
        )
        self.import_prv.scope_resource_ids.return_value = _discovery(
            [
                "/subscriptions/s/resourcegroups/rg-a",
                "/subscriptions/s/resourcegroups/RG-B",
            ]
        )

        discovery = await self.service.get_unmanaged_resources(
            scope_id="s",
            terraform_provider=TerraformProvider.AZURE,
        )

        # The scope's own spelling survives for the eventual import.
        self.assertEqual(
            discovery.resource_ids, ["/subscriptions/s/resourcegroups/RG-B"]
        )

    async def test_azure_case_variants_in_the_scope_are_listed_once(self):
        self.import_prv.state_resource_ids.return_value = _discovery([])
        self.import_prv.scope_resource_ids.return_value = _discovery(
            [
                "/subscriptions/s/resourceGroups/rg-a",
                "/subscriptions/s/resourcegroups/rg-a",
            ]
        )

        discovery = await self.service.get_unmanaged_resources(
            scope_id="s",
            terraform_provider=TerraformProvider.AZURE,
        )

        self.assertEqual(
            discovery.resource_ids, ["/subscriptions/s/resourceGroups/rg-a"]
        )

    async def test_non_azure_ids_compare_exactly(self):
        # GCP names can differ only by case and still be distinct
        # resources, so a lowercase match must not hide one as managed.
        self.import_prv.state_resource_ids.return_value = _discovery(
            ["projects/p/topics/Orders"]
        )
        self.import_prv.scope_resource_ids.return_value = _discovery(
            ["projects/p/topics/Orders", "projects/p/topics/orders"]
        )

        discovery = await self.service.get_unmanaged_resources(
            scope_id="p",
            terraform_provider=TerraformProvider.GCP,
        )

        self.assertEqual(discovery.resource_ids, ["projects/p/topics/orders"])

    # --- Import exceptions ---

    async def test_import_exceptions_are_withheld_and_reported(self):
        self.import_prv.state_resource_ids.return_value = _discovery([])
        self.import_prv.scope_resource_ids.return_value = _discovery(
            ["res-a", "res-b", "res-c"]
        )
        self.template_svc.render.return_value = _exception_list("res-b", "res-z")

        discovery = await self.service.get_unmanaged_resources(
            scope_id="scope-123",
            terraform_provider=TerraformProvider.GCP,
        )

        # Withheld in code on every round, so no caller and no selection
        # agent can bring it back; an exception absent from the scope is
        # simply not reported.
        self.assertEqual(discovery.resource_ids, ["res-a", "res-c"])
        self.assertEqual(discovery.excluded, ["res-b"])
        self.assertEqual(discovery.feedback, "")

    async def test_azure_import_exceptions_compare_case_insensitively(self):
        self.import_prv.state_resource_ids.return_value = _discovery([])
        self.import_prv.scope_resource_ids.return_value = _discovery(
            [
                "/subscriptions/s/resourcegroups/rg-a",
                "/subscriptions/s/resourcegroups/rg-b",
            ]
        )
        self.template_svc.render.return_value = _exception_list(
            "/subscriptions/s/resourceGroups/RG-A"
        )

        discovery = await self.service.get_unmanaged_resources(
            scope_id="s",
            terraform_provider=TerraformProvider.AZURE,
        )

        self.assertEqual(
            discovery.resource_ids, ["/subscriptions/s/resourcegroups/rg-b"]
        )
        # The report names the resource as the scope spells it.
        self.assertEqual(discovery.excluded, ["/subscriptions/s/resourcegroups/rg-a"])

    async def test_non_azure_import_exceptions_compare_exactly(self):
        self.import_prv.state_resource_ids.return_value = _discovery([])
        self.import_prv.scope_resource_ids.return_value = _discovery(
            ["projects/p/topics/orders"]
        )
        self.template_svc.render.return_value = _exception_list(
            "projects/p/topics/Orders"
        )

        discovery = await self.service.get_unmanaged_resources(
            scope_id="p",
            terraform_provider=TerraformProvider.GCP,
        )

        self.assertEqual(discovery.resource_ids, ["projects/p/topics/orders"])
        self.assertEqual(discovery.excluded, [])

    async def test_fully_withheld_scope_is_reported_apart_from_a_managed_one(self):
        self.import_prv.state_resource_ids.return_value = _discovery(["res-a"])
        self.import_prv.scope_resource_ids.return_value = _discovery(["res-a", "res-b"])
        self.template_svc.render.return_value = _exception_list("res-b")

        discovery = await self.service.get_unmanaged_resources(
            scope_id="scope-123",
            terraform_provider=TerraformProvider.AWS,
        )

        self.assertEqual(discovery.resource_ids, [])
        self.assertEqual(discovery.excluded, ["res-b"])
        self.assertIn("import exception list", discovery.feedback)

    async def test_import_exceptions_are_not_read_when_nothing_is_unmanaged(self):
        self.import_prv.state_resource_ids.return_value = _discovery(["res-a"])
        self.import_prv.scope_resource_ids.return_value = _discovery(["res-a"])

        discovery = await self.service.get_unmanaged_resources(
            scope_id="scope-123",
            terraform_provider=TerraformProvider.AZURE,
        )

        self.assertIn("already managed", discovery.feedback)
        self.template_svc.render.assert_not_awaited()

    async def test_import_exceptions_are_rendered_for_the_scope(self):
        self.import_prv.state_resource_ids.return_value = _discovery([])
        self.import_prv.scope_resource_ids.return_value = _discovery(["res-a"])

        await self.service.get_unmanaged_resources(
            scope_id="scope-123",
            terraform_provider=TerraformProvider.AZURE,
        )

        self.template_svc.render.assert_awaited_once_with(
            PromptsLibrary.IMPORT_EXCEPTIONS
        )

    async def test_import_exception_list_names_one_id_per_bullet(self):
        self.import_prv.state_resource_ids.return_value = _discovery([])
        self.import_prv.scope_resource_ids.return_value = _discovery(
            [
                "/subscriptions/s/resourceGroups/rg-a",
                "/subscriptions/s/resourceGroups/rg-b",
                "/subscriptions/s/resourceGroups/rg-c",
                "Resource IDs listed here are excluded.",
                "my-project roles/viewer user:a@example.com",
            ]
        )
        self.template_svc.render.return_value = _exceptions(
            "# Import Exception List\n"
            "\n"
            "Resource IDs listed here are excluded.\n"
            "- /subscriptions/s/resourceGroups/rg-a\n"
            "  * `/subscriptions/s/resourceGroups/rg-b`  \n"
            "- my-project roles/viewer user:a@example.com\n"
            "-\n"
            "- ``\n"
        )

        discovery = await self.service.get_unmanaged_resources(
            scope_id="s",
            terraform_provider=TerraformProvider.GCP,
        )

        # Prose and empty bullets are skipped; backticks and padding are
        # not part of the ID, inner spaces (GCP IAM members) are.
        self.assertEqual(
            discovery.excluded,
            [
                "/subscriptions/s/resourceGroups/rg-a",
                "/subscriptions/s/resourceGroups/rg-b",
                "my-project roles/viewer user:a@example.com",
            ],
        )
        self.assertEqual(
            discovery.resource_ids,
            [
                "/subscriptions/s/resourceGroups/rg-c",
                "Resource IDs listed here are excluded.",
            ],
        )

    async def test_seeded_import_exception_placeholders_name_no_id(self):
        # The seeds document the format with an inline example; it must not
        # parse as an exception on a fresh deployment.
        seed_dir = Path(__file__).resolve().parents[3] / "prompts" / "seed"
        for provider in ("azure", "gcp", "aws", "oci"):
            seed = seed_dir / provider / "guidelines" / "import_exceptions.yaml"
            self.template_svc.render.return_value = _exceptions(
                yaml.safe_load(seed.read_text())["body"]
            )
            self.import_prv.state_resource_ids.return_value = _discovery([])
            self.import_prv.scope_resource_ids.return_value = _discovery(["res-a"])

            discovery = await self.service.get_unmanaged_resources(
                scope_id="scope-123",
                terraform_provider=TerraformProvider(provider),
            )

            self.assertEqual(discovery.excluded, [], provider)

    # --- Import execution ---

    async def test_import_resources_partitions_the_round_by_result(self):
        self.import_prv.import_resource.side_effect = [
            _import_result(True),
            _import_result(False, "resource already managed"),
        ]

        outcome = await self.service.import_resources(
            [
                ("azurerm_resource_group.main", "res-1"),
                ("azurerm_storage_account.sta", "res-2"),
            ]
        )

        # The service keeps the address/resource id pairing it was given, so
        # the caller never has to recover it from the raw import results.
        self.assertEqual(
            [(a.address, a.resource_id, a.error) for a in outcome.imported],
            [("azurerm_resource_group.main", "res-1", "")],
        )
        self.assertEqual(
            [(a.address, a.resource_id, a.error) for a in outcome.failed],
            [("azurerm_storage_account.sta", "res-2", "resource already managed")],
        )
        self.assertEqual(outcome.addresses, ["azurerm_resource_group.main"])

    async def test_import_resources_with_nothing_to_import(self):
        outcome = await self.service.import_resources([])

        self.assertEqual(outcome.imported, [])
        self.assertEqual(outcome.failed, [])
        self.assertEqual(outcome.addresses, [])
        self.import_prv.import_resource.assert_not_awaited()
