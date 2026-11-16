# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Set up a root module's inputs once, then reuse them on every run.

The flow is: discover what the module needs from its code
(``IConfigInspector``), compare that with the manifest committed in the
module (``resolve_manifest``), ask the user only for what nothing covers,
and save their answers (``reconcile_manifest``). Plain values go into the
manifest, which travels with the code; sensitive ones go to the secret
store and the manifest keeps only their names.

Provider credentials are not inputs here: they keep arriving as the IaC
service's environment. A variable the platform injects (see
``platform_variables``) is never asked either.
"""

from collections.abc import Collection, Mapping, Sequence

from src.domains.exceptions import ManifestInputError, ManifestNotConfigured
from src.domains.interfaces.config_inspector_interface import IConfigInspector
from src.domains.interfaces.manifest_repository_interface import IManifestRepository
from src.domains.interfaces.manifest_secret_store_interface import (
    IManifestSecretStore,
)
from src.domains.value_objects.manifest import (
    JsonValue,
    Manifest,
    RootModuleRef,
    TerraformInputs,
    Variable,
    VariableAnswer,
)
from src.domains.value_objects.manifest_resolution import (
    ManifestResolution,
    ProviderChange,
)
from src.domains.value_objects.terraform_requirements import (
    ProviderRequirement,
    TerraformRequirements,
    VariableSpec,
)
from src.shared.constants import ManifestStatus, TerraformProvider

# Input variables the IaC service fills from the session's scope (its
# ``IacEngine._SCOPE_ENV_VARS``, the ``TF_VAR_*`` entries). Keep in sync.
_PLATFORM_VARIABLES: dict[TerraformProvider, frozenset[str]] = {
    TerraformProvider.OCI: frozenset({"compartment_ocid"}),
    TerraformProvider.AWS: frozenset({"aws_account_id"}),
}

_NOTHING: frozenset[str] = frozenset()
_LIST_TYPES = ("list", "set", "tuple")
_MAP_TYPES = ("map", "object")
_PRIMITIVE_TYPES = ("string", "number", "bool")


def platform_variables(provider: TerraformProvider | None) -> frozenset[str]:
    """Input variables the platform injects at run time for ``provider``."""
    return _PLATFORM_VARIABLES.get(provider, _NOTHING) if provider else _NOTHING


def resolve_manifest(
    requirements: TerraformRequirements,
    manifest: Manifest | None,
    provided: frozenset[str] = _NOTHING,
    *,
    stored_secrets: Collection[str],
) -> ManifestResolution:
    """Check ``manifest`` against the module's current ``requirements``.

    ``provided`` are the variables the platform injects; ``stored_secrets``
    the names whose values the secret store holds. A sensitive binding
    whose value is gone is reported missing even when the variable has a
    default, so a lost secret is asked again rather than silently replaced.
    """
    declared = {v.name: v for v in requirements.variables}
    selectable = {f.path for f in requirements.optional_var_files}
    selected = manifest.var_files if manifest else ()
    bindings = {v.name: v for v in manifest.variables} if manifest else {}

    lost = {n for n, b in bindings.items() if b.sensitive and n not in stored_secrets}
    covered = (
        {name for f in requirements.auto_var_files for name in f.assigns}
        | {
            name
            for f in requirements.optional_var_files
            if f.path in selected
            for name in f.assigns
        }
        | (bindings.keys() - lost)
        | provided
    )
    missing = tuple(
        spec
        for spec in requirements.variables
        if spec.name not in covered and (spec.required or spec.name in lost)
    )
    missing_files = tuple(p for p in selected if p not in selectable)
    stale = tuple(sorted(n for n in bindings if n not in declared))
    exposed = tuple(
        sorted(
            n
            for n, b in bindings.items()
            if n in declared and declared[n].sensitive and not b.sensitive
        )
    )

    if manifest is None:
        status = ManifestStatus.NOT_FOUND
    elif manifest.fingerprint == requirements.fingerprint and not (
        missing or missing_files or stale or exposed
    ):
        status = ManifestStatus.UP_TO_DATE
    else:
        status = ManifestStatus.DRIFTED

    return ManifestResolution(
        status=status,
        requirements=requirements,
        manifest=manifest,
        provided=provided,
        missing_variables=missing,
        missing_var_files=missing_files,
        stale_variables=stale,
        exposed_variables=exposed,
        provider_changes=(
            _provider_changes(manifest.providers, requirements.providers)
            if manifest
            else ()
        ),
    )


def reconcile_manifest(
    resolution: ManifestResolution,
    answers: Mapping[str, VariableAnswer],
    var_files: Sequence[str] | None,
    stored_secrets: Mapping[str, JsonValue],
) -> tuple[Manifest, dict[str, JsonValue]]:
    """The manifest and secret values that result from applying ``answers``.

    Starts from the resolution's manifest: bindings of variables no longer
    declared are dropped, plain values of variables now declared sensitive
    move to the secrets, and each answer replaces its variable's binding.
    ``var_files`` None keeps the current selection.

    Returns:
        The new manifest, fingerprinted against the current requirements,
        and every secret value the module now has (stale ones pruned).

    Raises:
        ManifestInputError: When an answer names an unknown variable or has
            the wrong shape, a var file cannot be selected, or something
            required is still left uncovered.
    """
    requirements = resolution.requirements
    declared = {v.name: v for v in requirements.variables}

    unknown = sorted(answers.keys() - declared.keys())
    if unknown:
        raise ManifestInputError(
            f"The root module declares no variable named: {', '.join(unknown)}.", 422
        )

    bindings: dict[str, Variable] = {}
    secrets: dict[str, JsonValue] = {}
    for binding in resolution.manifest.variables if resolution.manifest else ():
        spec = declared.get(binding.name)
        if spec is None:
            continue
        if binding.sensitive:
            bindings[binding.name] = binding
            if binding.name in stored_secrets:
                secrets[binding.name] = stored_secrets[binding.name]
        elif spec.sensitive:
            bindings[binding.name] = Variable(binding.name, sensitive=True)
            secrets[binding.name] = binding.value
        else:
            bindings[binding.name] = binding

    for name, answer in answers.items():
        spec = declared[name]
        _check_shape(spec, answer.value)
        current = bindings.get(name)
        if answer.sensitive is not None:
            sensitive = answer.sensitive
        else:
            sensitive = current.sensitive if current else spec.sensitive
        if sensitive or spec.sensitive:
            bindings[name] = Variable(name, sensitive=True)
            secrets[name] = answer.value
        else:
            bindings[name] = Variable(name, value=answer.value)
            _ = secrets.pop(name, None)

    manifest = Manifest(
        fingerprint=requirements.fingerprint,
        providers=requirements.providers,
        var_files=_select_var_files(resolution, var_files),
        variables=tuple(bindings[n] for n in sorted(bindings)),
    )

    check = resolve_manifest(
        requirements, manifest, resolution.provided, stored_secrets=secrets.keys()
    )
    if check.missing_variables or check.missing_var_files:
        raise ManifestInputError(_incomplete_message(check), 422)
    return manifest, secrets


class ManifestService:
    """Keeps a root module's manifest and secret values in step with its code."""

    def __init__(
        self,
        inspector: IConfigInspector,
        manifests: IManifestRepository,
        secrets: IManifestSecretStore,
    ):
        self.__inspector = inspector
        self.__manifests = manifests
        self.__secrets = secrets

    async def resolve(
        self, module: RootModuleRef, provided: frozenset[str] = _NOTHING
    ) -> ManifestResolution:
        """Where the module's manifest stands; reads only, never writes."""
        requirements, manifest = await self.__read(module)
        stored = await self.__stored_secrets(module, manifest)
        return resolve_manifest(
            requirements, manifest, provided, stored_secrets=stored.keys()
        )

    async def sync(
        self, module: RootModuleRef, provided: frozenset[str] = _NOTHING
    ) -> ManifestResolution:
        """Resolve, and save the manifest whenever that needs no answer from the user.

        Covers a first setup with nothing to ask and drift such as a
        provider bump, a removed variable or a variable newly declared
        sensitive. The returned resolution ``needs_input`` otherwise.
        """
        requirements, manifest = await self.__read(module)
        stored = await self.__stored_secrets(module, manifest)
        resolution = resolve_manifest(
            requirements, manifest, provided, stored_secrets=stored.keys()
        )
        if resolution.status is ManifestStatus.UP_TO_DATE or resolution.needs_input:
            return resolution
        return await self.__save(module, resolution, {}, None, stored)

    async def configure(
        self,
        module: RootModuleRef,
        answers: Mapping[str, VariableAnswer],
        var_files: Sequence[str] | None = None,
        provided: frozenset[str] = _NOTHING,
    ) -> ManifestResolution:
        """Apply the user's ``answers`` (and var file selection) and save the result.

        Raises:
            ManifestInputError: When the answers are invalid or leave
                something required uncovered; nothing is saved then.
        """
        requirements, manifest = await self.__read(module)
        stored = await self.__stored_secrets(module, manifest)
        resolution = resolve_manifest(
            requirements, manifest, provided, stored_secrets=stored.keys()
        )
        return await self.__save(module, resolution, answers, var_files, stored)

    async def inputs(self, module: RootModuleRef) -> TerraformInputs:
        """What a Terraform run of the module is given: var files and every bound value.

        Call after ``sync`` or ``configure`` reported the manifest up to
        date. A module without a manifest (one set up before manifests
        existed) is given nothing beyond what Terraform loads on its own.

        Raises:
            ManifestNotConfigured: When a secret value the manifest relies
                on is gone.
        """
        manifest = self.__manifests.load(module.directory)
        if manifest is None:
            return TerraformInputs()
        stored = await self.__stored_secrets(module, manifest)
        lost = [
            v.name for v in manifest.variables if v.sensitive and v.name not in stored
        ]
        if lost:
            raise ManifestNotConfigured(
                f"Secret values are missing for: {', '.join(lost)}.", 409
            )
        return TerraformInputs(
            var_files=manifest.var_files,
            values={
                v.name: stored[v.name] if v.sensitive else v.value
                for v in manifest.variables
            },
        )

    async def __read(
        self, module: RootModuleRef
    ) -> tuple[TerraformRequirements, Manifest | None]:
        requirements = await self.__inspector.inspect(module.directory)
        return requirements, self.__manifests.load(module.directory)

    async def __stored_secrets(
        self, module: RootModuleRef, manifest: Manifest | None
    ) -> dict[str, JsonValue]:
        if manifest is None or not any(v.sensitive for v in manifest.variables):
            return {}
        return await self.__secrets.load(module)

    async def __save(
        self,
        module: RootModuleRef,
        resolution: ManifestResolution,
        answers: Mapping[str, VariableAnswer],
        var_files: Sequence[str] | None,
        stored: dict[str, JsonValue],
    ) -> ManifestResolution:
        manifest, secrets = reconcile_manifest(resolution, answers, var_files, stored)
        # Secrets first: a manifest naming a secret that failed to save
        # would be reported as up to date with its value missing.
        if secrets != stored:
            await self.__secrets.save(module, secrets)
        if manifest != resolution.manifest:
            self.__manifests.save(module.directory, manifest)
        return resolve_manifest(
            resolution.requirements,
            manifest,
            resolution.provided,
            stored_secrets=secrets.keys(),
        )


def _select_var_files(
    resolution: ManifestResolution, var_files: Sequence[str] | None
) -> tuple[str, ...]:
    if var_files is None:
        return resolution.manifest.var_files if resolution.manifest else ()
    selectable = {f.path for f in resolution.selectable_var_files}
    rejected = sorted({p for p in var_files if p not in selectable})
    if rejected:
        raise ManifestInputError(
            f"Not an optional var file of the root module: {', '.join(rejected)}.", 422
        )
    if len(set(var_files)) != len(var_files):
        raise ManifestInputError("A var file is selected more than once.", 422)
    return tuple(var_files)


def _check_shape(spec: VariableSpec, value: JsonValue) -> None:
    """Reject a value whose shape cannot convert to the declared type.

    Only the outer shape is checked (list, map or primitive). Terraform
    converts between primitives and checks nested types itself.
    """
    if value is None or spec.type is None:
        return
    kind = spec.type.strip().strip('"').split("(", 1)[0].strip()
    if kind in _LIST_TYPES:
        ok = isinstance(value, list)
        expected = "a list"
    elif kind in _MAP_TYPES:
        ok = isinstance(value, dict)
        expected = "a map"
    elif kind in _PRIMITIVE_TYPES:
        ok = not isinstance(value, (list, dict))
        expected = f"a {kind}"
    else:  # any, or a type expression this check does not know
        return
    if not ok:
        raise ManifestInputError(
            f"Variable {spec.name!r} is declared {spec.type} and needs {expected}.", 422
        )


def _provider_changes(
    before: Sequence[ProviderRequirement], after: Sequence[ProviderRequirement]
) -> tuple[ProviderChange, ...]:
    old = {p.name: p for p in before}
    new = {p.name: p for p in after}
    return tuple(
        ProviderChange(name, old.get(name), new.get(name))
        for name in sorted(old.keys() | new.keys())
        if old.get(name) != new.get(name)
    )


def _incomplete_message(check: ManifestResolution) -> str:
    parts: list[str] = []
    if check.missing_variables:
        names = ", ".join(v.name for v in check.missing_variables)
        parts.append(f"values are still needed for: {names}")
    if check.missing_var_files:
        parts.append(
            f"selected var files no longer exist: {', '.join(check.missing_var_files)}"
        )
    return "The manifest is incomplete; " + "; ".join(parts) + "."
