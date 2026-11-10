# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import tempfile
import unittest
from pathlib import Path

from src.domains.value_objects import ManifestObject
from src.domains.value_objects.manifest_object import Backend, Fingerprint, Provider
from src.infrastructure.filesystem.manifest import Manifest

VALID_MANIFEST = """\
version: 1
backend:
  config: s3
  lineage: abc-123
fingerprint:
  checksum: deadbeef
  validated_at: 2026-11-09T10:00:00Z
providers:
  - name: hashicorp/aws
    version: 5.0.0
  - name: hashicorp/random
    version: 3.6.0
provider_env:
  - AWS_REGION
"""


class TestManifestLoad(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "manifest.yaml"

    def tearDown(self):
        self._tmp.cleanup()

    def test_parses_valid_manifest(self):
        self.path.write_text(VALID_MANIFEST)

        manifest = Manifest(self.path).load()

        self.assertEqual(manifest.version, "1")
        self.assertEqual(manifest.backend, Backend(config="s3", lineage="abc-123"))
        self.assertEqual(manifest.fingerprint.checksum, "deadbeef")
        self.assertIsInstance(manifest.fingerprint, Fingerprint)
        self.assertIsInstance(manifest.fingerprint.validated_at, str)
        self.assertEqual(
            manifest.providers,
            (Provider("hashicorp/aws", "5.0.0"), Provider("hashicorp/random", "3.6.0")),
        )
        self.assertEqual(manifest.provider_env, ("AWS_REGION",))

    def test_optional_sections_default_to_empty(self):
        self.path.write_text(
            "version: '1'\n"
            "backend: {config: s3, lineage: x}\n"
            "fingerprint: {checksum: c, validated_at: t}\n"
        )

        manifest = Manifest(self.path).load()

        self.assertEqual(manifest.providers, ())
        self.assertEqual(manifest.provider_env, ())

    def test_missing_file_returns_empty(self):
        self.assertEqual(Manifest(self.path).load(), ManifestObject.empty())

    def test_malformed_manifest_returns_empty(self):
        self.path.write_text("version: '1'\n")  # no backend / fingerprint

        self.assertEqual(Manifest(self.path).load(), ManifestObject.empty())

    def test_invalid_yaml_returns_empty(self):
        self.path.write_text("version: [unclosed\n")

        self.assertEqual(Manifest(self.path).load(), ManifestObject.empty())
