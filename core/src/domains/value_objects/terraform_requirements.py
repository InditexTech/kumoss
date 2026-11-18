# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import hashlib
import json
from dataclasses import dataclass, field
from functools import cached_property


@dataclass(frozen=True)
class ProviderRequirement:
    """Value object: one provider a root module depends on.

    ``name`` is the module-local name (``azurerm3``), ``source`` the
    registry address it resolves to (``terraform.local/local/azurerm3``).
    ``version_constraints`` are constraints as written (``~> 5.0``), not
    an installed version; the lock file pins that.
    """

    name: str
    source: str
    version_constraints: tuple[str, ...] = ()

    @property
    def type(self) -> str:
        """The provider type name: the source address's last segment (``azurerm``)."""
        return self.source.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class VariableSpec:
    """Value object: one input variable as the root module declares it.

    ``type`` is the HCL type expression as written (``map(string)``), or
    None when the variable is untyped. ``required`` means it has no
    default. ``description`` is shown to the user when asking for a value
    and is excluded from equality, so editing it is not a requirement change.
    """

    name: str
    type: str | None = None
    required: bool = False
    sensitive: bool = False
    description: str = field(default="", compare=False, repr=False)


@dataclass(frozen=True)
class VarFile:
    """Value object: one variable-definitions file found in a root module.

    ``path`` is POSIX and relative to the root module. ``auto`` files
    (``terraform.tfvars``, ``*.auto.tfvars`` and their ``.json`` forms at
    the module's top level) are loaded by Terraform on its own; the others
    only apply when passed as ``-var-file``. ``assigns`` holds the names of
    the variables the file sets, never their values.
    """

    path: str
    auto: bool
    assigns: frozenset[str] = frozenset()


@dataclass(frozen=True)
class TerraformRequirements:
    """Value object: everything a root module needs from outside, as discovered from its code.

    Built by inspecting the configuration, never entered by a user. Its
    ``fingerprint`` is what a manifest records to tell whether the
    configuration changed since the user last answered for it.
    """

    providers: tuple[ProviderRequirement, ...] = ()
    variables: tuple[VariableSpec, ...] = ()
    var_files: tuple[VarFile, ...] = ()

    def variable(self, name: str) -> VariableSpec | None:
        return next((v for v in self.variables if v.name == name), None)

    @property
    def provider_types(self) -> tuple[str, ...]:
        """Distinct provider type names, sorted (aliases of one type count once)."""
        return tuple(sorted({p.type for p in self.providers}))

    @property
    def auto_var_files(self) -> tuple[VarFile, ...]:
        return tuple(f for f in self.var_files if f.auto)

    @property
    def optional_var_files(self) -> tuple[VarFile, ...]:
        return tuple(f for f in self.var_files if not f.auto)

    @cached_property
    def fingerprint(self) -> str:
        """``sha256:<hex>`` over the parts of the requirements a user answers for.

        Covers providers, the variables' name/type/required/sensitive, which
        variables the auto-loaded files set, and which optional files exist.
        Descriptions, defaults and the contents of optional files are left
        out: changing them never changes what has to be asked.
        """
        canonical = {
            "providers": sorted(
                [p.name, p.source, sorted(p.version_constraints)]
                for p in self.providers
            ),
            "variables": sorted(
                [v.name, v.type, v.required, v.sensitive] for v in self.variables
            ),
            "auto_var_files": sorted(
                [f.path, sorted(f.assigns)] for f in self.auto_var_files
            ),
            "optional_var_files": sorted(f.path for f in self.optional_var_files),
        }
        digest = hashlib.sha256(
            json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
        return f"sha256:{digest}"
