# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import tempfile
import unittest
from pathlib import Path
from typing import override

from src.domains.exceptions import ManifestReadError
from src.domains.value_objects import (
    Manifest,
    ProviderRequirement,
    ProviderScope,
    Variable,
)
from src.infrastructure.filesystem.manifest_file import ManifestFile

MANIFEST = Manifest(
    fingerprint="sha256:abc",
    providers=(
        ProviderRequirement("aws", "hashicorp/aws", (">= 5.0",)),
        ProviderRequirement("random", "hashicorp/random"),
    ),
    var_files=("envs/dev.tfvars",),
    variables=(
        Variable("db_password", sensitive=True),
        Variable("owners", ["a", "b"]),
        Variable("region", {"location": "westeurope"}),
        Variable("released", "2026-01-01"),
        Variable("unset", None),
    ),
    scopes=(
        # Digits only: must survive YAML as a string.
        ProviderScope("aws", "123456789012"),
        ProviderScope("azurerm", "00000000-0000-0000-0000-000000000000"),
    ),
)


class TestManifestFile(unittest.TestCase):
    @override
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.file = ManifestFile("kumoss.yaml")

    @override
    def tearDown(self):
        self._tmp.cleanup()

    def write(self, text: str) -> None:
        _ = (self.dir / "kumoss.yaml").write_text(text)

    def test_missing_file_is_none(self):
        self.assertIsNone(self.file.load(self.dir))

    def test_round_trip(self):
        self.file.save(self.dir, MANIFEST)
        self.assertEqual(self.file.load(self.dir), MANIFEST)

    def test_saved_file_has_no_secret_values_and_no_leftovers(self):
        self.file.save(self.dir, MANIFEST)
        text = (self.dir / "kumoss.yaml").read_text()
        self.assertTrue(text.startswith("# Managed by Kumoss"))
        self.assertIn("name: db_password\n  sensitive: true\n", text)
        self.assertNotIn("\r", text)
        self.assertEqual([p.name for p in self.dir.iterdir()], ["kumoss.yaml"])

    def test_scopes_are_saved_by_provider_type(self):
        self.file.save(self.dir, MANIFEST)
        text = (self.dir / "kumoss.yaml").read_text()
        self.assertIn("scopes:\n", text)
        self.assertIn("- provider: azurerm\n", text)
        loaded = self.file.load(self.dir)
        self.assertEqual(loaded.scope("aws"), "123456789012")
        self.assertIsNone(loaded.scope("random"))

    def test_hand_written_scopes_are_read(self):
        self.write(
            "version: '1'\nfingerprint: sha256:x\n"
            "scopes:\n  - provider: google\n    scope_id: my-project\n"
        )
        self.assertEqual(
            self.file.load(self.dir).scopes, (ProviderScope("google", "my-project"),)
        )

    def test_unquoted_dates_stay_strings(self):
        self.write(
            "version: '1'\nfingerprint: sha256:x\n"
            "variables:\n  - name: released\n    value: 2026-01-01\n"
        )
        self.assertEqual(
            self.file.load(self.dir).variable("released").value, "2026-01-01"
        )

    def test_minimal_manifest(self):
        self.write("version: 1\nfingerprint: sha256:x\n")
        self.assertEqual(self.file.load(self.dir), Manifest(fingerprint="sha256:x"))

    def test_invalid_manifests_are_reported(self):
        cases = {
            "unsupported version": "version: '2'\nfingerprint: sha256:x\n",
            "fingerprint": "version: '1'\n",
            "must be a mapping": "- a\n- b\n",
            "must be a list": "version: '1'\nfingerprint: x\nvariables: {a: 1}\n",
            "non-empty string": "version: '1'\nfingerprint: x\nvariables:\n  - value: 1\n",
            "more than once": (
                "version: '1'\nfingerprint: x\nvariables:\n"
                "  - {name: a, value: 1}\n  - {name: a, value: 2}\n"
            ),
            "rotate the secret": (
                "version: '1'\nfingerprint: x\nvariables:\n"
                "  - {name: pw, sensitive: true, value: hunter2}\n"
            ),
            "Cannot read": "version: [unclosed\n",
            "more than one scope": (
                "version: '1'\nfingerprint: x\nscopes:\n"
                "  - {provider: azurerm, scope_id: a}\n"
                "  - {provider: azurerm, scope_id: b}\n"
            ),
            "'scope_id' must be a non-empty string": (
                "version: '1'\nfingerprint: x\nscopes:\n  - {provider: azurerm}\n"
            ),
            "'provider' must be a non-empty string": (
                "version: '1'\nfingerprint: x\nscopes:\n  - {scope_id: a}\n"
            ),
            "a scope must be a mapping": (
                "version: '1'\nfingerprint: x\nscopes:\n  - azurerm\n"
            ),
        }
        for expected, text in cases.items():
            with self.subTest(expected):
                self.write(text)
                with self.assertRaises(ManifestReadError) as ctx:
                    _ = self.file.load(self.dir)
                self.assertIn(expected, ctx.exception.message)
                self.assertEqual(ctx.exception.error_code, 422)
