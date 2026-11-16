# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

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
    repeated here.
    """

    fingerprint: str
    providers: tuple[ProviderRequirement, ...] = ()
    var_files: tuple[str, ...] = ()
    variables: tuple[Variable, ...] = ()

    def variable(self, name: str) -> Variable | None:
        return next((v for v in self.variables if v.name == name), None)


@dataclass(frozen=True)
class RootModuleRef:
    """Value object: one Terraform root module of one repository, and where it is checked out.

    ``repo_uri`` and ``path`` (POSIX, relative to the repository root) are
    the module's identity: every clone of the repository shares them.
    ``directory`` is this checkout's copy and is excluded from equality.
    """

    repo_uri: str
    path: str
    directory: Path = field(compare=False)

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

    ``var_files`` go first, as ``-var-file`` in order; ``values`` are
    written to one ``.tfvars.json`` passed after them, so they win.
    ``values`` include secrets: never log or persist this object.
    """

    var_files: tuple[str, ...] = ()
    values: dict[str, JsonValue] = field(default_factory=dict, repr=False)
