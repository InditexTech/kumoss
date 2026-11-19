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

The module's providers come from its code too: each scoped provider
(``SCOPED_PROVIDERS``) needs a scope id, asked once and kept in the
manifest; ``session_providers`` gives a session its provider/scope pairs.
Provider credentials are not inputs here: they keep arriving as the IaC
service's environment. A variable the platform injects for a provider's
scope (see ``platform_variables``) is never asked either.
"""

from collections.abc import Awaitable, Callable, Collection, Iterable, Mapping, Sequence

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
from src.domains.value_objects.provider_scope import ProviderScope
from src.domains.value_objects.manifest_resolution import (
    ManifestResolution,
    ProviderChange,
)
from src.domains.value_objects.terraform_requirements import (
    ProviderRequirement,
    TerraformRequirements,
    VariableSpec,
)
from src.shared.constants import SCOPE_BINDINGS, SCOPED_PROVIDERS, ManifestStatus

# Input variables each run fills from a provider's scope.
_PLATFORM_VARIABLES: dict[str, frozenset[str]] = {
    provider: frozenset({binding.name})
    for provider, binding in SCOPE_BINDINGS.items()
    if binding.kind == "var"
}

# Called with a session's provider/scope pairs before anything is saved;
# raises to stop the setup (authorization).
type Authorize = Callable[[tuple[ProviderScope, ...]], Awaitable[None]]

_NOTHING: frozenset[str] = frozenset()
_LIST_TYPES = ("list", "set", "tuple")
_MAP_TYPES = ("map", "object")
_PRIMITIVE_TYPES = ("string", "number", "bool")


def platform_variables(provider_types: Iterable[str]) -> frozenset[str]:
    """Input variables the platform injects at run time for these providers."""
    return frozenset().union(
        *(_PLATFORM_VARIABLES.get(t, _NOTHING) for t in provider_types)
    )


def session_providers(
    requirements: TerraformRequirements, manifest: Manifest | None
) -> tuple[ProviderScope, ...]:
    """Every provider type the module uses, with its saved scope when it has one."""
    return tuple(
        ProviderScope(
            t, manifest.scope(t) if manifest and t in SCOPED_PROVIDERS else None
        )
        for t in requirements.provider_types
    )


def resolve_manifest(
    requirements: TerraformRequirements,
    manifest: Manifest | None,
    *,
    stored_secrets: Collection[str],
) -> ManifestResolution:
    """Check ``manifest`` against the module's current ``requirements``.

    ``stored_secrets`` are the names whose values the secret store holds.
    A sensitive binding whose value is gone is reported missing even when
    the variable has a default, so a lost secret is asked again rather than
    silently replaced. Variables the platform injects for the module's
    providers are never reported missing.
    """
    provided = platform_variables(requirements.provider_types)
    declared = {v.name: v for v in requirements.variables}
    selectable = {f.path for f in requirements.optional_var_files}
    selected = manifest.var_files if manifest else ()
    bindings = {v.name: v for v in manifest.variables} if manifest else {}

    lost = {n for n, b in bindings.items() if b.sensitive and n not in stored_secrets}
    covered_without_selection = (
        {name for f in requirements.auto_var_files for name in f.assigns}
        | (bindings.keys() - lost)
        | provided
    )
    covered = covered_without_selection | {
        name
        for f in requirements.optional_var_files
        if f.path in selected
        for name in f.assigns
    }
    unanswered = tuple(
        spec
        for spec in requirements.variables
        if spec.name not in covered_without_selection
        and (spec.required or spec.name in lost)
    )
    missing = tuple(spec for spec in unanswered if spec.name not in covered)
    missing_files = tuple(p for p in selected if p not in selectable)
    stale = tuple(sorted(n for n in bindings if n not in declared))
    exposed = tuple(
        sorted(
            n
            for n, b in bindings.items()
            if n in declared and declared[n].sensitive and not b.sensitive
        )
    )
    scoped = {t for t in requirements.provider_types if t in SCOPED_PROVIDERS}
    have_scopes = {sc.provider for sc in manifest.scopes} if manifest else set()
    missing_scopes = tuple(sorted(scoped - have_scopes))
    stale_scopes = tuple(sorted(have_scopes - scoped))

    if manifest is None:
        status = ManifestStatus.NOT_FOUND
    elif manifest.fingerprint == requirements.fingerprint and not (
        missing or missing_files or stale or exposed or missing_scopes or stale_scopes
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
        unanswered_variables=unanswered,
        missing_var_files=missing_files,
        stale_variables=stale,
        exposed_variables=exposed,
        missing_scopes=missing_scopes,
        stale_scopes=stale_scopes,
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
    scopes: Mapping[str, str] | None = None,
) -> tuple[Manifest, dict[str, JsonValue]]:
    """The manifest and secret values that result from applying ``answers``.

    Starts from the resolution's manifest: bindings of variables no longer
    declared are dropped, plain values of variables now declared sensitive
    move to the secrets, and each answer replaces its variable's binding.
    ``var_files`` None keeps the current selection. ``scopes`` answer the
    scope id of scoped providers by type; scopes of providers the module no
    longer uses are dropped.

    Secret values are never pruned: the store is shared by every branch
    of the repository, and a value this branch no longer binds may still
    be bound on another one.

    Returns:
        The new manifest, fingerprinted against the current requirements,
        and the secret values: ``stored_secrets`` plus those set here.

    Raises:
        ManifestInputError: When an answer names an unknown variable, one
            the platform injects, or an unknown or unscoped provider, or has
            the wrong shape; when a var file cannot be selected; or when
            something required (a value or a scope) is still left uncovered.
    """
    requirements = resolution.requirements
    declared = {v.name: v for v in requirements.variables}
    merged_scopes = _merge_scopes(resolution, scopes or {})

    unknown = sorted(answers.keys() - declared.keys())
    if unknown:
        raise ManifestInputError(
            f"The root module declares no variable named: {', '.join(unknown)}.", 422
        )
    injected = sorted(answers.keys() & resolution.provided)
    if injected:
        raise ManifestInputError(
            f"Set by the platform from the session's scope: {', '.join(injected)}.",
            422,
        )

    bindings: dict[str, Variable] = {}
    secrets: dict[str, JsonValue] = dict(stored_secrets)
    for binding in resolution.manifest.variables if resolution.manifest else ():
        spec = declared.get(binding.name)
        if spec is None:
            continue
        if binding.sensitive:
            bindings[binding.name] = binding
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

    manifest = Manifest(
        fingerprint=requirements.fingerprint,
        providers=requirements.providers,
        var_files=_select_var_files(resolution, var_files),
        variables=tuple(bindings[n] for n in sorted(bindings)),
        scopes=merged_scopes,
    )

    check = resolve_manifest(requirements, manifest, stored_secrets=secrets.keys())
    if check.missing_variables or check.missing_var_files or check.missing_scopes:
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

    async def resolve(self, module: RootModuleRef) -> ManifestResolution:
        """Where the module's manifest stands; reads only, never writes."""
        requirements, manifest = await self.__read(module)
        stored = await self.__stored_secrets(module, manifest)
        return resolve_manifest(requirements, manifest, stored_secrets=stored.keys())

    async def sync(
        self, module: RootModuleRef, authorize: Authorize | None = None
    ) -> ManifestResolution:
        """Resolve, and save the manifest whenever that needs no answer from the user.

        Covers a first setup with nothing to ask and drift such as a
        provider bump, a removed variable or a variable newly declared
        sensitive. The returned resolution ``needs_input`` otherwise.
        ``authorize`` sees the session's provider/scope pairs before
        anything is written, and stops the setup by raising.
        """
        requirements, manifest = await self.__read(module)
        stored = await self.__stored_secrets(module, manifest)
        resolution = resolve_manifest(
            requirements, manifest, stored_secrets=stored.keys()
        )
        if resolution.needs_input:
            return resolution
        if resolution.status is ManifestStatus.UP_TO_DATE:
            if authorize is not None:
                await authorize(session_providers(requirements, manifest))
            return resolution
        return await self.__save(module, resolution, {}, None, stored, None, authorize)

    async def configure(
        self,
        module: RootModuleRef,
        answers: Mapping[str, VariableAnswer],
        var_files: Sequence[str] | None = None,
        scopes: Mapping[str, str] | None = None,
        authorize: Authorize | None = None,
    ) -> ManifestResolution:
        """Apply the user's ``answers``, var file selection and ``scopes``, and save.

        ``authorize`` sees the resulting provider/scope pairs before
        anything is written, and stops the setup by raising.

        Raises:
            ManifestInputError: When the answers are invalid or leave
                something required uncovered; nothing is saved then.
        """
        requirements, manifest = await self.__read(module)
        stored = await self.__stored_secrets(module, manifest)
        resolution = resolve_manifest(
            requirements, manifest, stored_secrets=stored.keys()
        )
        return await self.__save(
            module, resolution, answers, var_files, stored, scopes, authorize
        )

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
                "The Kumoss manifest names secrets whose values are missing: "
                + f"{', '.join(lost)}.",
                409,
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
        scopes: Mapping[str, str] | None,
        authorize: Authorize | None,
    ) -> ManifestResolution:
        manifest, secrets = reconcile_manifest(
            resolution, answers, var_files, stored, scopes
        )
        if authorize is not None:
            await authorize(session_providers(resolution.requirements, manifest))
        # Secrets first: a manifest naming a secret that failed to save
        # would be reported as up to date with its value missing.
        changed = {
            name: value
            for name, value in secrets.items()
            if name not in stored or stored[name] != value
        }
        if changed:
            await self.__save_secrets(module, changed)
        if manifest != resolution.manifest:
            self.__manifests.save(module.directory, manifest)
        return resolve_manifest(
            resolution.requirements, manifest, stored_secrets=secrets.keys()
        )

    async def __save_secrets(
        self, module: RootModuleRef, changed: Mapping[str, JsonValue]
    ) -> None:
        """Write ``changed`` over the latest stored values.

        Re-reading right before the write keeps values another session
        saved since this one loaded them (and those ``__stored_secrets``
        skips loading). It narrows the lost-write window; it does not close
        it, as the store has no conditional write.
        """
        latest = await self.__secrets.load(module)
        await self.__secrets.save(module, {**latest, **changed})


def _merge_scopes(
    resolution: ManifestResolution, answers: Mapping[str, str]
) -> tuple[ProviderScope, ...]:
    scoped = {
        t for t in resolution.requirements.provider_types if t in SCOPED_PROVIDERS
    }
    unknown = sorted(answers.keys() - scoped)
    if unknown:
        raise ManifestInputError(
            f"The root module uses no scoped provider named: {', '.join(unknown)}.", 422
        )
    merged = {
        sc.provider: sc.scope_id
        for sc in (resolution.manifest.scopes if resolution.manifest else ())
        if sc.provider in scoped and sc.scope_id
    }
    for provider, scope_id in answers.items():
        if not scope_id.strip():
            raise ManifestInputError(f"The scope for {provider} is empty.", 422)
        merged[provider] = scope_id.strip()
    return tuple(ProviderScope(p, merged[p]) for p in sorted(merged))


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
    if check.missing_scopes:
        parts.append(f"scopes are still needed for: {', '.join(check.missing_scopes)}")
    return "The Kumoss manifest is incomplete; " + "; ".join(parts) + "."
