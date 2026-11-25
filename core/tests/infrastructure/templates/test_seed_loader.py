# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic
import tempfile
import unittest
from pathlib import Path

from src.infrastructure.exceptions import PromptSeedLoadError
from src.infrastructure.templates._seed_loader import SeedLoader


def _write(root: Path, rel: str, content: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


class TestSeedLoader(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_loads_valid_entry_and_derives_qualified_name(self):
        _write(
            self.root,
            "azurerm/guidelines/networking.yaml",
            "description: Net rules\nbody: |\n  Use hub-and-spoke.\n",
        )
        entries = SeedLoader(self.root).load()
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e.scope, "azurerm")
        self.assertEqual(e.type, "guidelines")
        self.assertEqual(e.name, "networking")
        self.assertEqual(e.qualified_name, "azurerm/guidelines/networking")
        self.assertEqual(e.description, "Net rules")
        self.assertIn("hub-and-spoke", e.body)

    def test_description_optional(self):
        _write(self.root, "general/guidelines/terraform.yaml", "body: anything\n")
        entries = SeedLoader(self.root).load()
        self.assertIsNone(entries[0].description)

    def test_missing_seed_dir_raises(self):
        with self.assertRaises(PromptSeedLoadError) as ctx:
            SeedLoader(self.root / "nope").load()
        self.assertIn("does not exist", ctx.exception.message)

    def test_empty_seed_dir_returns_empty_list(self):
        self.assertEqual(SeedLoader(self.root).load(), [])

    def test_rejects_unknown_scope(self):
        for bad in ("OnPrem", "-azurerm", "azure rm", "azure.rm"):
            with self.subTest(bad):
                root = self.root / f"case-{abs(hash(bad))}"
                _write(root, f"{bad}/guidelines/foo.yaml", "body: x\n")
                with self.assertRaises(PromptSeedLoadError) as ctx:
                    SeedLoader(root).load()
                self.assertIn(f"Invalid scope '{bad}'", ctx.exception.message)

    def test_accepts_every_provider_scope(self):
        # "general" or any Terraform provider type name.
        names = {"general", "azurerm", "google", "aws", "oci", "kubernetes", "vsphere"}
        names |= {"random", "helm", "my_provider-2"}
        for scope in names:
            _write(self.root, f"{scope}/guidelines/networking.yaml", "body: x\n")
        scopes = {e.scope for e in SeedLoader(self.root).load()}
        self.assertEqual(scopes, names)

    def test_rejects_unknown_type(self):
        _write(self.root, "azurerm/snippets/foo.yaml", "body: x\n")
        with self.assertRaises(PromptSeedLoadError) as ctx:
            SeedLoader(self.root).load()
        self.assertIn("Invalid type 'snippets'", ctx.exception.message)

    def test_rejects_wrong_depth(self):
        _write(self.root, "azurerm/foo.yaml", "body: x\n")
        with self.assertRaises(PromptSeedLoadError) as ctx:
            SeedLoader(self.root).load()
        self.assertIn("<scope>/<type>/<name>.<ext>", ctx.exception.message)

    def test_rejects_invalid_name(self):
        _write(self.root, "azurerm/guidelines/Bad-Name.yaml", "body: x\n")
        with self.assertRaises(PromptSeedLoadError) as ctx:
            SeedLoader(self.root).load()
        self.assertIn("Invalid prompt name", ctx.exception.message)

    def test_rejects_empty_body(self):
        _write(self.root, "azurerm/guidelines/foo.yaml", 'body: "   "\n')
        with self.assertRaises(PromptSeedLoadError) as ctx:
            SeedLoader(self.root).load()
        self.assertIn("must be a non-empty string", ctx.exception.message)

    def test_rejects_missing_body(self):
        _write(self.root, "azurerm/guidelines/foo.yaml", "description: only\n")
        with self.assertRaises(PromptSeedLoadError) as ctx:
            SeedLoader(self.root).load()
        self.assertIn("must be a non-empty string", ctx.exception.message)

    def test_rejects_malformed_yaml(self):
        _write(self.root, "azurerm/guidelines/foo.yaml", "body: [unclosed\n")
        with self.assertRaises(PromptSeedLoadError) as ctx:
            SeedLoader(self.root).load()
        self.assertIn("YAML parse error", ctx.exception.message)

    def test_rejects_non_mapping_yaml(self):
        _write(self.root, "azurerm/guidelines/foo.yaml", "- just\n- a\n- list\n")
        with self.assertRaises(PromptSeedLoadError) as ctx:
            SeedLoader(self.root).load()
        self.assertIn("must be a mapping", ctx.exception.message)

    def test_loads_full_tree_in_sorted_order(self):
        _write(self.root, "azurerm/guidelines/networking.yaml", "body: n\n")
        _write(self.root, "azurerm/guidelines/permissions.yaml", "body: p\n")
        _write(self.root, "general/guidelines/terraform.yaml", "body: t\n")
        names = [e.qualified_name for e in SeedLoader(self.root).load()]
        self.assertEqual(
            names,
            [
                "azurerm/guidelines/networking",
                "azurerm/guidelines/permissions",
                "general/guidelines/terraform",
            ],
        )

    def test_loads_a_policy_whole_file_as_its_body(self):
        rego = (
            "# a comment\npackage kumoss.compliance\n\ndeny contains x if { false }\n"
        )
        _write(self.root, "general/policies/compliance.rego", rego)
        [entry] = SeedLoader(self.root).load()
        self.assertEqual(entry.qualified_name, "general/policies/compliance")
        self.assertEqual(entry.body, rego)
        self.assertIsNotNone(entry.description)

    def test_ignores_files_that_are_neither_yaml_nor_rego(self):
        _write(self.root, "general/policies/README.md", "notes")
        self.assertEqual(SeedLoader(self.root).load(), [])

    def test_rejects_a_policy_outside_policies(self):
        _write(self.root, "general/compliance/rules.rego", "package x\n")
        with self.assertRaises(PromptSeedLoadError) as ctx:
            SeedLoader(self.root).load()
        self.assertIn("must be .yaml files", ctx.exception.message)

    def test_rejects_yaml_under_policies(self):
        _write(self.root, "general/policies/compliance.yaml", "body: x\n")
        with self.assertRaises(PromptSeedLoadError) as ctx:
            SeedLoader(self.root).load()
        self.assertIn("must be .rego files", ctx.exception.message)

    def test_rejects_an_empty_policy(self):
        _write(self.root, "general/policies/compliance.rego", "  \n")
        with self.assertRaises(PromptSeedLoadError) as ctx:
            SeedLoader(self.root).load()
        self.assertIn("is empty", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
