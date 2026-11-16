# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Manifest resolution and reconciliation: what is asked, what is kept, where values go.

The rules are pure functions over value objects and are tested as such;
``ManifestService`` is tested with in-memory ports for its I/O ordering.
"""

import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import override

from src.domains.exceptions import ManifestInputError, ManifestNotConfigured
from src.domains.interfaces import (
    IConfigInspector,
    IManifestRepository,
    IManifestSecretStore,
)
from src.domains.services.manifest_service import (
    ManifestService,
    platform_variables,
    reconcile_manifest,
    resolve_manifest,
)
from src.domains.value_objects import (
    Manifest,
    ProviderRequirement,
    RootModuleRef,
    TerraformInputs,
    TerraformRequirements,
    VarFile,
    Variable,
    VariableAnswer,
    VariableSpec,
)
from src.domains.value_objects.manifest import JsonValue
from src.shared.constants import ManifestStatus, TerraformProvider

AWS = ProviderRequirement("aws", "hashicorp/aws", (">= 5.0",))
RANDOM = ProviderRequirement("random", "hashicorp/random")

REGION = VariableSpec("region", "map(string)", required=True)
DB_PASSWORD = VariableSpec("db_password", "string", required=True, sensitive=True)
OWNERS = VariableSpec("owners", "list(string)")
NAME = VariableSpec("name", "string", required=True)


def requirements(
    variables: tuple[VariableSpec, ...] = (REGION, DB_PASSWORD, OWNERS),
    var_files: tuple[VarFile, ...] = (),
    providers: tuple[ProviderRequirement, ...] = (AWS,),
) -> TerraformRequirements:
    return TerraformRequirements(
        providers=providers, variables=variables, var_files=var_files
    )


def configured(
    req: TerraformRequirements, secrets: Mapping[str, JsonValue] | None = None
) -> tuple[Manifest, dict[str, JsonValue]]:
    """A manifest fully configured for ``req`` with region and db_password answered."""
    resolution = resolve_manifest(req, None, stored_secrets=())
    return reconcile_manifest(
        resolution,
        {
            "region": VariableAnswer({"location": "westeurope"}),
            "db_password": VariableAnswer("s3cr3t"),
        },
        None,
        secrets or {},
    )


class TestFingerprint(unittest.TestCase):
    def test_ignores_descriptions_and_order(self):
        a = requirements(variables=(REGION, OWNERS))
        b = requirements(
            variables=(
                VariableSpec("owners", "list(string)", description="changed"),
                REGION,
            )
        )
        self.assertEqual(a.fingerprint, b.fingerprint)

    def test_changes_when_what_is_asked_changes(self):
        base = requirements().fingerprint
        self.assertNotEqual(base, requirements(variables=(REGION,)).fingerprint)
        self.assertNotEqual(
            base,
            requirements(
                providers=(ProviderRequirement("aws", "hashicorp/aws", ("~> 6.0",)),)
            ).fingerprint,
        )
        self.assertNotEqual(
            base,
            requirements(
                var_files=(VarFile("terraform.tfvars", True, frozenset({"region"})),)
            ).fingerprint,
        )

    def test_ignores_contents_of_optional_var_files(self):
        a = requirements(
            var_files=(VarFile("envs/dev.tfvars", False, frozenset({"a"})),)
        )
        b = requirements(
            var_files=(VarFile("envs/dev.tfvars", False, frozenset({"b"})),)
        )
        self.assertEqual(a.fingerprint, b.fingerprint)


class TestResolve(unittest.TestCase):
    def test_first_setup_asks_only_uncovered_required_variables(self):
        req = requirements(
            variables=(REGION, DB_PASSWORD, OWNERS, NAME),
            var_files=(VarFile("terraform.tfvars", True, frozenset({"name"})),),
        )
        res = resolve_manifest(req, None, stored_secrets=())
        self.assertIs(res.status, ManifestStatus.NOT_FOUND)
        self.assertEqual(
            [v.name for v in res.missing_variables], ["region", "db_password"]
        )
        self.assertTrue(res.needs_input)

    def test_platform_injected_variables_are_never_asked(self):
        req = requirements(
            variables=(VariableSpec("compartment_ocid", "string", required=True),)
        )
        provided = platform_variables(TerraformProvider.OCI)
        res = resolve_manifest(req, None, provided, stored_secrets=())
        self.assertEqual(res.missing_variables, ())
        self.assertFalse(res.needs_input)
        self.assertEqual(platform_variables(None), frozenset())

    def test_first_setup_asks_for_var_files_when_there_are_some(self):
        req = requirements(
            variables=(),
            var_files=(VarFile("envs/dev.tfvars", False, frozenset()),),
        )
        res = resolve_manifest(req, None, stored_secrets=())
        self.assertTrue(res.needs_input)
        manifest, _ = reconcile_manifest(res, {}, [], {})
        self.assertFalse(resolve_manifest(req, manifest, stored_secrets=()).needs_input)

    def test_configured_manifest_is_up_to_date(self):
        req = requirements()
        manifest, secrets = configured(req)
        res = resolve_manifest(req, manifest, stored_secrets=secrets.keys())
        self.assertIs(res.status, ManifestStatus.UP_TO_DATE)
        self.assertFalse(res.needs_input)

    def test_provider_bump_drifts_without_asking(self):
        manifest, secrets = configured(requirements())
        bumped = requirements(
            providers=(ProviderRequirement("aws", "hashicorp/aws", ("~> 6.0",)), RANDOM)
        )
        res = resolve_manifest(bumped, manifest, stored_secrets=secrets.keys())
        self.assertIs(res.status, ManifestStatus.DRIFTED)
        self.assertFalse(res.needs_input)
        self.assertEqual([c.name for c in res.provider_changes], ["aws", "random"])
        self.assertIsNone(res.provider_changes[1].before)

    def test_new_required_variable_is_the_only_question(self):
        manifest, secrets = configured(requirements())
        grown = requirements(variables=(REGION, DB_PASSWORD, OWNERS, NAME))
        res = resolve_manifest(grown, manifest, stored_secrets=secrets.keys())
        self.assertIs(res.status, ManifestStatus.DRIFTED)
        self.assertEqual([v.name for v in res.missing_variables], ["name"])

    def test_lost_secret_is_asked_again_even_with_a_default(self):
        optional_secret = VariableSpec("token", "string", sensitive=True)
        req = requirements(variables=(optional_secret,))
        manifest = Manifest(
            fingerprint=req.fingerprint,
            providers=req.providers,
            variables=(Variable("token", sensitive=True),),
        )
        res = resolve_manifest(req, manifest, stored_secrets=())
        self.assertEqual([v.name for v in res.missing_variables], ["token"])
        self.assertIs(res.status, ManifestStatus.DRIFTED)

    def test_vanished_var_file_needs_input(self):
        req = requirements(variables=(), var_files=(VarFile("envs/dev.tfvars", False),))
        manifest, _ = reconcile_manifest(
            resolve_manifest(req, None, stored_secrets=()), {}, ["envs/dev.tfvars"], {}
        )
        res = resolve_manifest(requirements(variables=()), manifest, stored_secrets=())
        self.assertEqual(res.missing_var_files, ("envs/dev.tfvars",))
        self.assertTrue(res.needs_input)

    def test_selected_var_file_covers_its_variables(self):
        req = requirements(
            variables=(REGION,),
            var_files=(VarFile("envs/dev.tfvars", False, frozenset({"region"})),),
        )
        manifest, _ = reconcile_manifest(
            resolve_manifest(req, None, stored_secrets=()), {}, ["envs/dev.tfvars"], {}
        )
        self.assertEqual(manifest.variables, ())
        self.assertIs(
            resolve_manifest(req, manifest, stored_secrets=()).status,
            ManifestStatus.UP_TO_DATE,
        )


class TestReconcile(unittest.TestCase):
    def test_sensitive_values_never_reach_the_manifest(self):
        manifest, secrets = configured(requirements())
        self.assertEqual(
            manifest.variable("db_password"), Variable("db_password", sensitive=True)
        )
        self.assertEqual(secrets, {"db_password": "s3cr3t"})
        self.assertEqual(manifest.variable("region").value, {"location": "westeurope"})

    def test_user_can_mark_a_plain_variable_sensitive(self):
        req = requirements()
        res = resolve_manifest(req, None, stored_secrets=())
        manifest, secrets = reconcile_manifest(
            res,
            {
                "region": VariableAnswer({"location": "x"}, sensitive=True),
                "db_password": VariableAnswer("pw"),
            },
            None,
            {},
        )
        self.assertTrue(manifest.variable("region").sensitive)
        self.assertEqual(secrets["region"], {"location": "x"})

    def test_declared_sensitive_cannot_be_downgraded(self):
        res = resolve_manifest(requirements(), None, stored_secrets=())
        manifest, secrets = reconcile_manifest(
            res,
            {
                "region": VariableAnswer({}),
                "db_password": VariableAnswer("pw", sensitive=False),
            },
            None,
            {},
        )
        self.assertTrue(manifest.variable("db_password").sensitive)
        self.assertIn("db_password", secrets)

    def test_answer_keeps_current_classification_by_default(self):
        req = requirements(variables=(OWNERS,))
        res = resolve_manifest(req, None, stored_secrets=())
        manifest, secrets = reconcile_manifest(
            res, {"owners": VariableAnswer(["a"], sensitive=True)}, None, {}
        )
        res = resolve_manifest(req, manifest, stored_secrets=secrets.keys())
        manifest, secrets = reconcile_manifest(
            res, {"owners": VariableAnswer(["b"])}, None, secrets
        )
        self.assertTrue(manifest.variable("owners").sensitive)
        self.assertEqual(secrets, {"owners": ["b"]})

    def test_explicit_downgrade_moves_value_back_to_the_manifest(self):
        req = requirements(variables=(OWNERS,))
        res = resolve_manifest(req, None, stored_secrets=())
        manifest, secrets = reconcile_manifest(
            res, {"owners": VariableAnswer(["a"], sensitive=True)}, None, {}
        )
        res = resolve_manifest(req, manifest, stored_secrets=secrets.keys())
        manifest, secrets = reconcile_manifest(
            res, {"owners": VariableAnswer(["a"], sensitive=False)}, None, secrets
        )
        self.assertEqual(manifest.variable("owners"), Variable("owners", ["a"]))
        self.assertEqual(secrets, {})

    def test_variable_newly_declared_sensitive_moves_to_secrets(self):
        plain = requirements(variables=(OWNERS,))
        manifest, _ = reconcile_manifest(
            resolve_manifest(plain, None, stored_secrets=()),
            {"owners": VariableAnswer(["a"])},
            None,
            {},
        )
        now_sensitive = requirements(
            variables=(VariableSpec("owners", "list(string)", sensitive=True),)
        )
        res = resolve_manifest(now_sensitive, manifest, stored_secrets=())
        self.assertEqual(res.exposed_variables, ("owners",))
        self.assertFalse(res.needs_input)
        manifest, secrets = reconcile_manifest(res, {}, None, {})
        self.assertEqual(
            manifest.variable("owners"), Variable("owners", sensitive=True)
        )
        self.assertEqual(secrets, {"owners": ["a"]})

    def test_removed_variables_are_pruned_with_their_secrets(self):
        manifest, secrets = configured(requirements())
        shrunk = requirements(variables=(REGION,))
        res = resolve_manifest(shrunk, manifest, stored_secrets=secrets.keys())
        self.assertEqual(res.stale_variables, ("db_password",))
        manifest, secrets = reconcile_manifest(res, {}, None, secrets)
        self.assertEqual([v.name for v in manifest.variables], ["region"])
        self.assertEqual(secrets, {})

    def test_incomplete_answers_are_rejected_with_the_missing_names(self):
        res = resolve_manifest(requirements(), None, stored_secrets=())
        with self.assertRaises(ManifestInputError) as ctx:
            _ = reconcile_manifest(res, {"region": VariableAnswer({})}, None, {})
        self.assertIn("db_password", ctx.exception.message)
        self.assertEqual(ctx.exception.error_code, 422)

    def test_unknown_variable_is_rejected(self):
        res = resolve_manifest(requirements(), None, stored_secrets=())
        with self.assertRaises(ManifestInputError) as ctx:
            _ = reconcile_manifest(res, {"nope": VariableAnswer(1)}, None, {})
        self.assertIn("nope", ctx.exception.message)

    def test_wrong_shape_is_rejected(self):
        res = resolve_manifest(requirements(), None, stored_secrets=())
        with self.assertRaises(ManifestInputError) as ctx:
            _ = reconcile_manifest(
                res,
                {
                    "region": VariableAnswer("westeurope"),
                    "db_password": VariableAnswer("pw"),
                },
                None,
                {},
            )
        self.assertIn("map(string)", ctx.exception.message)

    def test_shape_check_accepts_what_terraform_converts(self):
        req = requirements(
            variables=(
                VariableSpec("n", "number"),
                VariableSpec("o", "object({ a = string })"),
                VariableSpec("legacy", '"list"'),
                VariableSpec("anything", "any"),
                VariableSpec("untyped"),
            )
        )
        res = resolve_manifest(req, None, stored_secrets=())
        manifest, _ = reconcile_manifest(
            res,
            {
                "n": VariableAnswer("3"),
                "o": VariableAnswer({"a": "x"}),
                "legacy": VariableAnswer([1]),
                "anything": VariableAnswer([{"x": 1}]),
                "untyped": VariableAnswer({"y": 2}),
            },
            None,
            {},
        )
        self.assertEqual(len(manifest.variables), 5)

    def test_only_optional_var_files_can_be_selected(self):
        req = requirements(
            variables=(),
            var_files=(
                VarFile("terraform.tfvars", True),
                VarFile("envs/dev.tfvars", False),
            ),
        )
        res = resolve_manifest(req, None, stored_secrets=())
        for selection in (
            ["terraform.tfvars"],
            ["../x.tfvars"],
            ["envs/dev.tfvars"] * 2,
        ):
            with self.assertRaises(ManifestInputError):
                _ = reconcile_manifest(res, {}, selection, {})

    def test_var_file_order_is_kept(self):
        req = requirements(
            variables=(),
            var_files=(VarFile("a.tfvars", False), VarFile("b.tfvars", False)),
        )
        res = resolve_manifest(req, None, stored_secrets=())
        manifest, _ = reconcile_manifest(res, {}, ["b.tfvars", "a.tfvars"], {})
        self.assertEqual(manifest.var_files, ("b.tfvars", "a.tfvars"))


class TestValueObjects(unittest.TestCase):
    def test_sensitive_variable_cannot_hold_a_value(self):
        with self.assertRaises(ValueError):
            _ = Variable("x", "leak", sensitive=True)

    def test_root_module_path_is_normalized_and_contained(self):
        self.assertEqual(RootModuleRef("r", "./a/b/", Path("/w")).path, "a/b")
        self.assertEqual(RootModuleRef("r", "", Path("/w")).path, ".")
        for bad in ("../x", "/abs", "a/../../b"):
            with self.assertRaises(ValueError):
                _ = RootModuleRef("r", bad, Path("/w"))

    def test_root_module_identity_ignores_the_checkout(self):
        self.assertEqual(
            RootModuleRef("r", "a", Path("/one")), RootModuleRef("r", "a", Path("/two"))
        )


class FakeInspector(IConfigInspector):
    def __init__(self, req: TerraformRequirements):
        self.requirements = req

    @override
    async def inspect(self, directory: Path) -> TerraformRequirements:
        return self.requirements


class FakeManifests(IManifestRepository):
    def __init__(self):
        self.stored: Manifest | None = None
        self.saves = 0

    @override
    def load(self, directory: Path) -> Manifest | None:
        return self.stored

    @override
    def save(self, directory: Path, manifest: Manifest) -> None:
        self.stored = manifest
        self.saves += 1


class FakeSecrets(IManifestSecretStore):
    def __init__(self, fail: bool = False):
        self.values: dict[str, JsonValue] = {}
        self.loads = 0
        self.fail = fail

    @override
    async def load(self, module: RootModuleRef) -> dict[str, JsonValue]:
        self.loads += 1
        return dict(self.values)

    @override
    async def save(
        self, module: RootModuleRef, values: Mapping[str, JsonValue]
    ) -> None:
        if self.fail:
            raise RuntimeError("store down")
        self.values = dict(values)


MODULE = RootModuleRef("https://example.com/org/repo", "infra", Path("/tmp/x"))


class TestManifestService(unittest.IsolatedAsyncioTestCase):
    @override
    def setUp(self):
        self.inspector = FakeInspector(requirements())
        self.manifests = FakeManifests()
        self.secrets = FakeSecrets()
        self.service = ManifestService(self.inspector, self.manifests, self.secrets)

    async def configure(self):
        return await self.service.configure(
            MODULE,
            {
                "region": VariableAnswer({"location": "westeurope"}),
                "db_password": VariableAnswer("s3cr3t"),
            },
        )

    async def test_full_cycle(self):
        res = await self.service.sync(MODULE)
        self.assertIs(res.status, ManifestStatus.NOT_FOUND)
        self.assertTrue(res.needs_input)
        self.assertIsNone(self.manifests.stored)

        res = await self.configure()
        self.assertIs(res.status, ManifestStatus.UP_TO_DATE)
        self.assertEqual(self.secrets.values, {"db_password": "s3cr3t"})

        inputs = await self.service.inputs(MODULE)
        self.assertEqual(
            inputs.values,
            {"db_password": "s3cr3t", "region": {"location": "westeurope"}},
        )
        self.assertNotIn("s3cr3t", repr(inputs))

        saves = self.manifests.saves
        res = await self.service.sync(MODULE)
        self.assertIs(res.status, ManifestStatus.UP_TO_DATE)
        self.assertEqual(self.manifests.saves, saves)

    async def test_sync_heals_drift_that_needs_no_answer(self):
        _ = await self.configure()
        self.inspector.requirements = requirements(providers=(AWS, RANDOM))
        self.assertIs(
            (await self.service.resolve(MODULE)).status, ManifestStatus.DRIFTED
        )
        res = await self.service.sync(MODULE)
        self.assertIs(res.status, ManifestStatus.UP_TO_DATE)
        self.assertIn(RANDOM, self.manifests.stored.providers)

    async def test_sync_creates_manifest_when_nothing_to_ask(self):
        self.inspector.requirements = requirements(variables=(OWNERS,))
        res = await self.service.sync(MODULE)
        self.assertIs(res.status, ManifestStatus.UP_TO_DATE)
        self.assertIsNotNone(self.manifests.stored)

    async def test_secret_store_is_not_read_without_sensitive_bindings(self):
        self.inspector.requirements = requirements(variables=(REGION,))
        _ = await self.service.configure(MODULE, {"region": VariableAnswer({})})
        _ = await self.service.resolve(MODULE)
        _ = await self.service.inputs(MODULE)
        self.assertEqual(self.secrets.loads, 0)

    async def test_manifest_is_not_written_when_secrets_fail(self):
        self.secrets.fail = True
        with self.assertRaises(RuntimeError):
            _ = await self.configure()
        self.assertIsNone(self.manifests.stored)

    async def test_inputs_require_a_complete_configuration(self):
        self.assertEqual(await self.service.inputs(MODULE), TerraformInputs())
        _ = await self.configure()
        self.secrets.values = {}
        with self.assertRaises(ManifestNotConfigured) as ctx:
            _ = await self.service.inputs(MODULE)
        self.assertIn("db_password", ctx.exception.message)
