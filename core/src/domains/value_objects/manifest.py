# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from src.domains.value_objects.provider_scope import ProviderScope
from src.domains.value_objects.terraform_requirements import ProviderRequirement

# A Terraform input value as it travels through JSON/YAML: a primitive,
# a list or a string-keyed map of them. Kept as ``Any`` at runtime.
type JsonValue = Any


@dataclass(frozen=True)
class Variable:
    """Value object: the value a root module's input variable is bound to.

    A ``sensitive`` binding never carries its value: the value lives in
    the secret store and ``value`` stays None, so a manifest can be
    committed without leaking it.
    """

    name: str
    value: JsonValue = None
    sensitive: bool = False

    def __post_init__(self) -> None:
        if self.sensitive and self.value is not None:
            raise ValueError(
                f"sensitive variable {self.name!r} must not carry its value"
            )


@dataclass(frozen=True)
class Manifest:
    """Value object: the inputs a root module was configured with.

    ``fingerprint`` is the one of the requirements it was built against;
    ``providers`` is a copy of them kept for the record and for reporting
    what changed. ``var_files`` are the optional ``-var-file`` files the
    user picked, in the order they are passed. ``variables`` holds only
    what the user answered: defaults and values set by var files are not
    repeated here. ``scopes`` are the user's scope ids for the scoped
    providers of the module, one per provider type.

    ``project_identifier`` is the name the user gave the repository when
    it is not the repository URL itself (a bare name the mapping service
    resolved). It is informational: refreshed on every save, never
    compared against the current call.
    """

    fingerprint: str
    providers: tuple[ProviderRequirement, ...] = ()
    var_files: tuple[str, ...] = ()
    variables: tuple[Variable, ...] = ()
    scopes: tuple[ProviderScope, ...] = ()
    project_identifier: str | None = None

    def variable(self, name: str) -> Variable | None:
        return next((v for v in self.variables if v.name == name), None)

    def scope(self, provider: str) -> str | None:
        return next((s.scope_id for s in self.scopes if s.provider == provider), None)


@dataclass(frozen=True)
class RootModuleRef:
    """Value object: one Terraform root module of one repository, and where it is checked out.

    ``repo_uri`` and ``path`` (POSIX, relative to the repository root) are
    the module's identity: every clone of the repository shares them.
    ``directory`` is this checkout's copy and is excluded from equality.
    ``project_identifier`` is the name the user gave the repository before
    the mapping service resolved it to ``repo_uri``, None when there is
    none; it is not part of the identity either.
    """

    repo_uri: str
    path: str
    directory: Path = field(compare=False)
    project_identifier: str | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        normalized = PurePosixPath(self.path.strip() or ".").as_posix()
        if PurePosixPath(normalized).is_absolute() or ".." in normalized.split("/"):
            raise ValueError(
                f"root module path {self.path!r} must stay inside the repository"
            )
        object.__setattr__(self, "path", normalized)


@dataclass(frozen=True)
class VariableAnswer:
    """Value object: a user's answer for one input variable.

    ``sensitive`` None keeps the variable's current classification (its
    binding's, else its declaration's). A variable the code declares
    sensitive is always stored as a secret, whatever is asked here.
    """

    value: JsonValue
    sensitive: bool | None = None


@dataclass(frozen=True)
class TerraformInputs:
    """Value object: what a Terraform run of a configured root module is given.

    ``var_files`` go first, as ``-var-file`` in order, read by Terraform
    itself on every command; ``values`` follow as one more variables
    file, so they win. Files Terraform loads on its own still apply
    underneath. ``values`` include secrets: never log or persist this
    object.
    """

    var_files: tuple[str, ...] = ()
    values: dict[str, JsonValue] = field(default_factory=dict, repr=False)
