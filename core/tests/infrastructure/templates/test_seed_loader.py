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
            "azure/guidelines/networking.yaml",
            "description: Net rules\nbody: |\n  Use hub-and-spoke.\n",
        )
        entries = SeedLoader(self.root).load()
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e.scope, "azure")
        self.assertEqual(e.type, "guidelines")
        self.assertEqual(e.name, "networking")
        self.assertEqual(e.qualified_name, "azure-guidelines-networking")
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
        _write(self.root, "aws/guidelines/foo.yaml", "body: x\n")
        with self.assertRaises(PromptSeedLoadError) as ctx:
            SeedLoader(self.root).load()
        self.assertIn("Invalid scope 'aws'", ctx.exception.message)

    def test_rejects_unknown_type(self):
        _write(self.root, "azure/snippets/foo.yaml", "body: x\n")
        with self.assertRaises(PromptSeedLoadError) as ctx:
            SeedLoader(self.root).load()
        self.assertIn("Invalid type 'snippets'", ctx.exception.message)

    def test_rejects_wrong_depth(self):
        _write(self.root, "azure/foo.yaml", "body: x\n")
        with self.assertRaises(PromptSeedLoadError) as ctx:
            SeedLoader(self.root).load()
        self.assertIn("<scope>/<type>/<name>.yaml", ctx.exception.message)

    def test_rejects_invalid_name(self):
        _write(self.root, "azure/guidelines/Bad-Name.yaml", "body: x\n")
        with self.assertRaises(PromptSeedLoadError) as ctx:
            SeedLoader(self.root).load()
        self.assertIn("Invalid prompt name", ctx.exception.message)

    def test_rejects_empty_body(self):
        _write(self.root, "azure/guidelines/foo.yaml", 'body: "   "\n')
        with self.assertRaises(PromptSeedLoadError) as ctx:
            SeedLoader(self.root).load()
        self.assertIn("must be a non-empty string", ctx.exception.message)

    def test_rejects_missing_body(self):
        _write(self.root, "azure/guidelines/foo.yaml", "description: only\n")
        with self.assertRaises(PromptSeedLoadError) as ctx:
            SeedLoader(self.root).load()
        self.assertIn("must be a non-empty string", ctx.exception.message)

    def test_rejects_malformed_yaml(self):
        _write(self.root, "azure/guidelines/foo.yaml", "body: [unclosed\n")
        with self.assertRaises(PromptSeedLoadError) as ctx:
            SeedLoader(self.root).load()
        self.assertIn("YAML parse error", ctx.exception.message)

    def test_rejects_non_mapping_yaml(self):
        _write(self.root, "azure/guidelines/foo.yaml", "- just\n- a\n- list\n")
        with self.assertRaises(PromptSeedLoadError) as ctx:
            SeedLoader(self.root).load()
        self.assertIn("must be a mapping", ctx.exception.message)

    def test_loads_full_tree_in_sorted_order(self):
        _write(self.root, "azure/guidelines/networking.yaml", "body: n\n")
        _write(self.root, "azure/guidelines/permissions.yaml", "body: p\n")
        _write(self.root, "general/guidelines/terraform.yaml", "body: t\n")
        names = [e.qualified_name for e in SeedLoader(self.root).load()]
        self.assertEqual(
            names,
            [
                "azure-guidelines-networking",
                "azure-guidelines-permissions",
                "general-guidelines-terraform",
            ],
        )


if __name__ == "__main__":
    unittest.main()
