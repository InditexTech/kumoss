# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass

from src.domains.value_objects.manifest import Manifest
from src.domains.value_objects.terraform_requirements import (
    ProviderRequirement,
    TerraformRequirements,
    VarFile,
    VariableSpec,
)
from src.shared.constants import ManifestStatus


@dataclass(frozen=True)
class ProviderChange:
    """Value object: a provider added (``before`` None), removed (``after`` None) or changed."""

    name: str
    before: ProviderRequirement | None
    after: ProviderRequirement | None


@dataclass(frozen=True)
class ManifestResolution:
    """Value object: a root module's manifest checked against its current configuration.

    ``missing_variables`` are required variables nothing covers (no var
    file, binding or platform injection): the user has to answer them.
    ``unanswered_variables`` adds those only a picked optional var file
    covers: unpicking that file makes them missing again.
    ``missing_var_files`` were picked by the user but no longer exist.
    ``stale_variables`` are bound but no longer declared, and
    ``exposed_variables`` are bound in plain text but now declared
    sensitive; both are fixed without asking on the next save.
    ``provided`` are the variables the platform injects at run time.
    """

    status: ManifestStatus
    requirements: TerraformRequirements
    manifest: Manifest | None
    provided: frozenset[str] = frozenset()
    missing_variables: tuple[VariableSpec, ...] = ()
    unanswered_variables: tuple[VariableSpec, ...] = ()
    missing_var_files: tuple[str, ...] = ()
    stale_variables: tuple[str, ...] = ()
    exposed_variables: tuple[str, ...] = ()
    provider_changes: tuple[ProviderChange, ...] = ()

    @property
    def selectable_var_files(self) -> tuple[VarFile, ...]:
        """Optional var files the user can pick from."""
        return self.requirements.optional_var_files

    @property
    def needs_input(self) -> bool:
        """Whether only the user can bring the manifest up to date.

        A first setup asks when there are optional var files to pick from;
        afterwards that choice is kept and only missing values are asked.
        """
        if self.missing_variables or self.missing_var_files:
            return True
        return self.manifest is None and bool(self.selectable_var_files)
