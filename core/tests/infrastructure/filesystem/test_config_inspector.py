# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""TerraformConfigInspector: mapping the CLI's output, and scanning var files.

The parsing helpers are tested on recorded output. The end-to-end cases
run the real terraform-config-inspect and are skipped when it is not on
PATH (it is in the core image).
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from typing import override

from src.domains.value_objects import ProviderRequirement, VarFile, VariableSpec
from src.infrastructure.exceptions import ConfigInspectionError, InvalidRootModulePath
from src.infrastructure.filesystem.config_inspector import (
    TerraformConfigInspector,
    _parse_providers,
    _parse_variables,
    _scan_var_files,
)

MAIN_TF = """\
terraform {
  required_providers {
    aws = { source = "registry.terraform.io/HashiCorp/aws", version = "< 6.0, >= 5.0" }
    mirror = { source = "terraform.local/local/azurerm3", version = "= 3.85.0" }
  }
}
variable "region" { type = map(string) }
variable "secret" {
  type      = string
  sensitive = true
}
variable "untyped" {}
variable "optional" {
  type        = string
  default     = null
  description = "  An optional one.  "
}
resource "random_id" "x" { byte_length = 2 }
"""


class TestParse(unittest.TestCase):
    def test_providers(self):
        parsed = _parse_providers(
            {
                "random": {},
                "aws": {
                    "source": "registry.terraform.io/hashicorp/aws",
                    "version_constraints": ["~> 5.0", ">= 5.1"],
                },
                "tofu": {"source": "registry.opentofu.org/hashicorp/null"},
            }
        )
        self.assertEqual(
            parsed,
            (
                ProviderRequirement("aws", "hashicorp/aws", (">= 5.1", "~> 5.0")),
                ProviderRequirement("random", "hashicorp/random"),
                ProviderRequirement("tofu", "hashicorp/null"),
            ),
        )
        self.assertEqual(_parse_providers(None), ())

    def test_variables(self):
        parsed = _parse_variables(
            {
                "b": {"type": None, "required": True, "sensitive": None},
                "a": {
                    "type": "string",
                    "required": False,
                    "sensitive": True,
                    "description": " d ",
                },
            }
        )
        self.assertEqual(
            parsed,
            (
                VariableSpec("a", "string", required=False, sensitive=True),
                VariableSpec("b", None, required=True, sensitive=False),
            ),
        )
        self.assertEqual(parsed[0].description, "d")

    def test_multi_line_types_are_normalized(self):
        parsed = _parse_variables(
            {
                "o": {
                    "type": "object({\n    a = string\n    b = optional(bool, true)\n  })"
                }
            }
        )
        self.assertEqual(
            parsed[0].type, "object({ a = string b = optional(bool, true) })"
        )


class TestScanVarFiles(unittest.TestCase):
    @override
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    @override
    def tearDown(self):
        self._tmp.cleanup()

    def put(self, rel: str, text: str = "") -> None:
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text(text)

    def test_classifies_and_reads_names_only(self):
        self.put("main.tf")
        self.put(
            "terraform.tfvars",
            'region = { location = "x" }\n# c = 1\nlong = <<EOT\nnot = this\nEOT\n',
        )
        self.put("terraform.tfvars.json", '{"j": 1}')
        self.put("z.auto.tfvars", "z = 1")
        self.put("envs/dev.tfvars", "dev = true")
        self.put("envs/a/b/c/too_deep.tfvars", "x = 1")
        self.put("envs/sub.auto.tfvars", "s = 1")
        self.put(".terraform/hidden.tfvars", "h = 1")
        self.put("modules/net/main.tf")
        self.put("modules/net/net.tfvars", "n = 1")

        files = {f.path: f for f in _scan_var_files(self.dir)}
        self.assertEqual(
            sorted(files),
            [
                "envs/dev.tfvars",
                "envs/sub.auto.tfvars",
                "terraform.tfvars",
                "terraform.tfvars.json",
                "z.auto.tfvars",
            ],
        )
        self.assertEqual(
            files["terraform.tfvars"],
            VarFile("terraform.tfvars", True, frozenset({"region", "long"})),
        )
        self.assertEqual(files["terraform.tfvars.json"].assigns, frozenset({"j"}))
        self.assertTrue(files["z.auto.tfvars"].auto)
        # Terraform only auto-loads from the module's own directory.
        self.assertFalse(files["envs/sub.auto.tfvars"].auto)
        self.assertEqual(files["envs/dev.tfvars"].assigns, frozenset({"dev"}))

    def test_any_file_name_is_offered(self):
        # The core reads picked files itself, so no path shape is excluded.
        self.put("envs/my env.tfvars", "a = 1")
        self.put("envs/ok.tfvars", "a = 1")
        self.assertEqual(
            [f.path for f in _scan_var_files(self.dir)],
            ["envs/my env.tfvars", "envs/ok.tfvars"],
        )

    def test_names_starting_with_underscores_are_kept(self):
        self.put("terraform.tfvars", "__size = 4\n# a comment\n")
        self.put("envs/x.tfvars.json", '{"__region": "weu"}')
        files = {f.path: f.assigns for f in _scan_var_files(self.dir)}
        self.assertEqual(
            files,
            {
                "terraform.tfvars": frozenset({"__size"}),
                "envs/x.tfvars.json": frozenset({"__region"}),
            },
        )

    def test_unreadable_optional_file_is_ignored(self):
        self.put("envs/bad.tfvars", "this is { not hcl")
        self.assertEqual(
            _scan_var_files(self.dir), (VarFile("envs/bad.tfvars", False),)
        )

    def test_unreadable_auto_file_is_an_error(self):
        self.put("terraform.tfvars.json", "[1, 2]")
        with self.assertRaises(ConfigInspectionError):
            _ = _scan_var_files(self.dir)

    def test_symlinks_are_not_followed(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        _ = (Path(outside.name) / "x.tfvars").write_text("x = 1")
        (self.dir / "link.tfvars").symlink_to(Path(outside.name) / "x.tfvars")
        (self.dir / "linkdir").symlink_to(outside.name)
        self.assertEqual(_scan_var_files(self.dir), ())


@unittest.skipUnless(
    shutil.which("terraform-config-inspect"),
    "terraform-config-inspect is not installed",
)
class TestInspectEndToEnd(unittest.IsolatedAsyncioTestCase):
    @override
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    @override
    def tearDown(self):
        self._tmp.cleanup()

    async def test_inspects_a_module(self):
        _ = (self.dir / "main.tf").write_text(MAIN_TF)
        _ = (self.dir / "terraform.tfvars").write_text('region = { a = "b" }\n')
        req = await TerraformConfigInspector().inspect(self.dir)

        self.assertEqual(
            req.providers,
            (
                ProviderRequirement("aws", "hashicorp/aws", ("< 6.0, >= 5.0",)),
                ProviderRequirement(
                    "mirror", "terraform.local/local/azurerm3", ("= 3.85.0",)
                ),
                ProviderRequirement("random", "hashicorp/random"),
            ),
        )
        self.assertEqual(
            req.variables,
            (
                VariableSpec("optional", "string"),
                VariableSpec("region", "map(string)", required=True),
                VariableSpec("secret", "string", required=True, sensitive=True),
                VariableSpec("untyped", None, required=True),
            ),
        )
        self.assertEqual(req.variable("optional").description, "An optional one.")
        self.assertEqual(
            req.auto_var_files,
            (VarFile("terraform.tfvars", True, frozenset({"region"})),),
        )

    async def test_syntax_errors_are_reported(self):
        _ = (self.dir / "main.tf").write_text('variable "x" {\n')
        with self.assertRaises(ConfigInspectionError) as ctx:
            _ = await TerraformConfigInspector().inspect(self.dir)
        self.assertEqual(ctx.exception.error_code, 422)
        self.assertIn("main.tf:1", ctx.exception.message)

    async def test_not_a_module(self):
        for target in (self.dir, self.dir / "missing"):
            with self.subTest(str(target)):
                with self.assertRaises(InvalidRootModulePath):
                    _ = await TerraformConfigInspector().inspect(target)


class TestMissingBinary(unittest.IsolatedAsyncioTestCase):
    async def test_reports_missing_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            _ = (Path(tmp) / "main.tf").write_text("")
            with self.assertRaises(ConfigInspectionError) as ctx:
                _ = await TerraformConfigInspector(binary="no-such-binary-x").inspect(
                    Path(tmp)
                )
            self.assertIn("not installed", ctx.exception.message)
