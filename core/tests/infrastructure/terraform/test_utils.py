# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic, reportAssignmentType=false, reportAttributeAccessIssue=false
import unittest

from src.infrastructure.terraform.utils import TerraformUtils


def _make_plan(resource_changes: list[dict]) -> dict:
    """Build a minimal Terraform plan JSON with the given resource_changes."""
    return {
        "format_version": "1.2",
        "resource_changes": resource_changes,
    }


def _make_resource(address: str, actions: list[str], before: dict, after: dict) -> dict:
    return {
        "address": address,
        "change": {
            "actions": actions,
            "before": before,
            "after": after,
        },
    }


class TestPlanToDriftTagValues(unittest.TestCase):
    """Tests for tag value preservation in plan_to_drift."""

    def test_tag_removed_includes_value(self):
        """When individual tags are removed, the diff must include the removed values."""
        before = {
            "name": "my-resource",
            "tags": {
                "environment": "pro",
                "compliance": "high",
                "datacloud": "v1",
            },
        }
        after = {
            "name": "my-resource",
            "tags": {
                "environment": "pro",
            },
        }
        plan = _make_plan(
            [_make_resource("azurerm_resource.test", ["update"], before, after)]
        )

        result = TerraformUtils.plan_to_drift(plan)

        self.assertEqual(len(result), 1)
        changes = result[0]["changes"]
        self.assertIn("dictionary_item_removed", changes)
        removed = changes["dictionary_item_removed"]
        # Must be a dict (with values), not a list (paths only)
        self.assertIsInstance(removed, dict)
        # Verify the actual tag values are present
        self.assertEqual(removed["root['tags']['compliance']"], "high")
        self.assertEqual(removed["root['tags']['datacloud']"], "v1")

    def test_tag_added_includes_value(self):
        """When individual tags are added, the diff must include the added values."""
        before = {
            "name": "my-resource",
            "tags": {
                "environment": "pro",
            },
        }
        after = {
            "name": "my-resource",
            "tags": {
                "environment": "pro",
                "compliance": "high",
                "project": "pixia",
            },
        }
        plan = _make_plan(
            [_make_resource("azurerm_resource.test", ["update"], before, after)]
        )

        result = TerraformUtils.plan_to_drift(plan)

        self.assertEqual(len(result), 1)
        changes = result[0]["changes"]
        self.assertIn("dictionary_item_added", changes)
        added = changes["dictionary_item_added"]
        self.assertIsInstance(added, dict)
        self.assertEqual(added["root['tags']['compliance']"], "high")
        self.assertEqual(added["root['tags']['project']"], "pixia")

    def test_tag_value_changed_includes_old_and_new(self):
        """When a tag value changes, both old and new values must be present."""
        before = {
            "name": "my-resource",
            "tags": {"environment": "dev"},
        }
        after = {
            "name": "my-resource",
            "tags": {"environment": "pro"},
        }
        plan = _make_plan(
            [_make_resource("azurerm_resource.test", ["update"], before, after)]
        )

        result = TerraformUtils.plan_to_drift(plan)

        self.assertEqual(len(result), 1)
        changes = result[0]["changes"]
        self.assertIn("values_changed", changes)
        tag_change = changes["values_changed"]["root['tags']['environment']"]
        self.assertEqual(tag_change["old_value"], "dev")
        self.assertEqual(tag_change["new_value"], "pro")

    def test_entire_tags_object_replaced(self):
        """When the entire tags dict changes, values_changed should carry both dicts."""
        before = {
            "name": "my-resource",
            "tags": {},
        }
        after = {
            "name": "my-resource",
            "tags": {"environment": "pro", "project": "pixia"},
        }
        plan = _make_plan(
            [_make_resource("azurerm_resource.test", ["update"], before, after)]
        )

        result = TerraformUtils.plan_to_drift(plan)

        self.assertEqual(len(result), 1)
        changes = result[0]["changes"]
        self.assertIn("values_changed", changes)
        tags_change = changes["values_changed"]["root['tags']"]
        self.assertEqual(tags_change["old_value"], {})
        self.assertEqual(
            tags_change["new_value"], {"environment": "pro", "project": "pixia"}
        )

    def test_mixed_tag_and_attribute_changes(self):
        """Tags and non-tag attributes drifting in the same resource."""
        before = {
            "name": "my-resource",
            "sku": "Standard",
            "tags": {"environment": "pro", "old_tag": "remove-me"},
        }
        after = {
            "name": "my-resource",
            "sku": "Premium",
            "tags": {"environment": "pro", "new_tag": "added"},
        }
        plan = _make_plan(
            [_make_resource("azurerm_resource.test", ["update"], before, after)]
        )

        result = TerraformUtils.plan_to_drift(plan)

        self.assertEqual(len(result), 1)
        changes = result[0]["changes"]
        # SKU change
        sku_change = changes["values_changed"]["root['sku']"]
        self.assertEqual(sku_change["old_value"], "Standard")
        self.assertEqual(sku_change["new_value"], "Premium")
        # Tag removed with value
        removed = changes["dictionary_item_removed"]
        self.assertIsInstance(removed, dict)
        self.assertEqual(removed["root['tags']['old_tag']"], "remove-me")
        # Tag added with value
        added = changes["dictionary_item_added"]
        self.assertIsInstance(added, dict)
        self.assertEqual(added["root['tags']['new_tag']"], "added")

    def test_reversed_tag_drift_swaps_added_removed(self):
        """Reversed output should swap added/removed and old/new for tags."""
        before = {
            "name": "my-resource",
            "tags": {"keep": "yes", "removed_tag": "gone"},
        }
        after = {
            "name": "my-resource",
            "tags": {"keep": "yes"},
        }
        plan = _make_plan(
            [_make_resource("azurerm_resource.test", ["update"], before, after)]
        )

        result = TerraformUtils.plan_to_drift(plan, reversed=True)

        self.assertEqual(len(result), 1)
        changes = result[0]["changes"]
        # Reversed: removed becomes added
        self.assertIn("dictionary_item_added", changes)
        self.assertNotIn("dictionary_item_removed", changes)

    def test_reversed_keeps_values_and_paths_with_keywords(self):
        """Reversal must not rewrite old/new/added/removed inside values or paths."""
        before = {
            "name": "stappnew1ba2edc3",
            "tags": {"keep": "yes", "removed_tag": "golden"},
        }
        after = {
            "name": "stappold1ba2edc3",
            "tags": {"keep": "yes", "new_tag": "renewal"},
        }
        plan = _make_plan(
            [
                _make_resource(
                    "azurerm_resource.test", ["delete", "create"], before, after
                )
            ]
        )

        result = TerraformUtils.plan_to_drift(plan, reversed=True)

        changes = result[0]["changes"]
        self.assertEqual(
            changes["values_changed"]["root['name']"],
            {"old_value": "stappold1ba2edc3", "new_value": "stappnew1ba2edc3"},
        )
        self.assertEqual(
            changes["dictionary_item_added"], {"root['tags']['removed_tag']": "golden"}
        )
        self.assertEqual(
            changes["dictionary_item_removed"], {"root['tags']['new_tag']": "renewal"}
        )

    def test_no_drift_when_tags_identical(self):
        """No output when before and after tags are the same."""
        resource_data = {
            "name": "my-resource",
            "tags": {"environment": "pro"},
        }
        plan = _make_plan(
            [
                _make_resource(
                    "azurerm_resource.test", ["update"], resource_data, resource_data
                )
            ]
        )

        result = TerraformUtils.plan_to_drift(plan)

        self.assertEqual(len(result), 0)


class TestProjectId(unittest.TestCase):
    """Tests for the state-keying identifier sent to the IaC service."""

    REPO = "https://github.example.com/org/infra.git"
    SCOPE = "11111111-2222-3333-4444-555555555555"
    PATH = "envs/prod"

    def _id(self, repo=REPO, scope=SCOPE, path=PATH) -> str:
        return TerraformUtils.project_id(repo_uri=repo, scope_id=scope, iac_path=path)

    def test_is_a_sha256_hex_digest(self):
        """The IaC contract types project_id as 64 lowercase hex chars."""
        project_id = self._id()

        self.assertEqual(len(project_id), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in project_id))

    def test_is_stable_across_calls(self):
        """Two runs of the same project must land on the same state."""
        self.assertEqual(self._id(), self._id())

    def test_each_part_of_the_triple_changes_it(self):
        """Repository, scope and root module each identify the project:
        a different value in any of them is a different state."""
        baseline = self._id()

        self.assertNotEqual(
            baseline, self._id(repo="https://github.example.com/org/other.git")
        )
        self.assertNotEqual(
            baseline, self._id(scope="99999999-2222-3333-4444-555555555555")
        )
        self.assertNotEqual(baseline, self._id(path="envs/dev"))

    def test_same_path_in_different_repos_differs(self):
        """The repository is in the seed precisely for this: a shared
        root module name in one cloud scope must not collide."""
        self.assertNotEqual(
            self._id(repo="https://github.example.com/org/a.git", path=""),
            self._id(repo="https://github.example.com/org/b.git", path=""),
        )

    def test_repo_uri_spelling_does_not_split_a_project(self):
        """The same repository reaches here in whatever form the caller
        used; credentials embedded for push, a .git suffix, a trailing
        slash or a different case must all resolve to one project."""
        baseline = self._id()

        for variant in (
            "https://github.example.com/org/infra",
            "https://github.example.com/org/infra/",
            "https://x-access-token:ghp_secret@github.example.com/org/infra.git",
            "HTTPS://GitHub.Example.com/Org/Infra.git",
            "  https://github.example.com/org/infra.git  ",
        ):
            with self.subTest(variant=variant):
                self.assertEqual(baseline, self._id(repo=variant))

    def test_ssh_and_https_remotes_agree(self):
        """A clone over SSH and one over HTTPS are the same project."""
        self.assertEqual(
            self._id(repo="git@github.example.com:org/infra.git"),
            self._id(repo="https://github.example.com/org/infra.git"),
        )

    def test_iac_path_spelling_does_not_split_a_project(self):
        baseline = self._id()

        for variant in ("/envs/prod", "envs/prod/", "  envs/prod  ", "envs//prod"):
            with self.subTest(variant=variant):
                self.assertEqual(baseline, self._id(path=variant))

    def test_repository_root_is_a_valid_project(self):
        """An empty iac_path means the root module is the repository
        root — a project like any other, not a missing value."""
        for empty in ("", "/", "   "):
            with self.subTest(empty=empty):
                self.assertEqual(self._id(path=""), self._id(path=empty))


if __name__ == "__main__":
    unittest.main()
