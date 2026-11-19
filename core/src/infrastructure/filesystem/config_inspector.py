# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Discover a root module's requirements with HashiCorp's terraform-config-inspect.

The tool statically reads the module's ``.tf`` files (no ``init``, no
provider download) and reports its variables and providers. It does not
read variable-definition files, so those are scanned here: the ones
Terraform loads on its own and the ones a user may pass as ``-var-file``.

terraform-config-inspect exits 0 with an empty result for a directory
that does not exist, so the directory is checked before running it.
"""

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any, cast, final, override

import hcl2

from src.domains.interfaces.config_inspector_interface import IConfigInspector
from src.domains.value_objects.terraform_requirements import (
    ProviderRequirement,
    TerraformRequirements,
    VarFile,
    VariableSpec,
)
from src.infrastructure.exceptions import ConfigInspectionError, InvalidRootModulePath
from src.infrastructure.filesystem.cli import Cli
from src.shared.logger import logging

_AUTO_VAR_FILES = frozenset({"terraform.tfvars", "terraform.tfvars.json"})
_AUTO_VAR_SUFFIXES = (".auto.tfvars", ".auto.tfvars.json")
_VAR_FILE_SUFFIXES = (".tfvars", ".tfvars.json")
_MODULE_SUFFIXES = (".tf", ".tf.json")
# Registry hosts a bare ``namespace/type`` source already implies.
_DEFAULT_REGISTRIES = ("registry.terraform.io/", "registry.opentofu.org/")
# How deep under the module to look for optional var files (``envs/dev.tfvars``).
_MAX_VAR_FILE_DEPTH = 3


@final
class TerraformConfigInspector(IConfigInspector):
    """``IConfigInspector`` backed by the terraform-config-inspect CLI."""

    def __init__(self, binary: str = "terraform-config-inspect", timeout: int = 60):
        self.__binary = binary
        self.__timeout = timeout

    @override
    async def inspect(self, directory: Path) -> TerraformRequirements:
        if not _is_module(directory):
            raise InvalidRootModulePath(
                message=f"'{directory.name}' is not a Terraform module: it has no .tf files",
                error_code=400,
            )
        data = await self.__run(directory)
        var_files = await asyncio.to_thread(_scan_var_files, directory)
        return TerraformRequirements(
            providers=_parse_providers(data.get("required_providers")),
            variables=_parse_variables(data.get("variables")),
            var_files=var_files,
        )

    async def __run(self, directory: Path) -> dict[str, Any]:
        if shutil.which(self.__binary) is None:
            raise ConfigInspectionError(f"{self.__binary} is not installed", 500)
        result = await Cli(cwd=str(directory)).execute(
            [self.__binary, "--json", "."], self.__timeout
        )
        try:
            data: Any = json.loads(result.stdout)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise ConfigInspectionError(
                f"{self.__binary} returned no readable result: {stderr or e}", 500
            ) from e
        if not isinstance(data, dict):
            raise ConfigInspectionError(
                f"{self.__binary} returned an unexpected result", 500
            )
        payload = cast(dict[str, Any], data)

        errors: list[str] = []
        diagnostics: list[dict[str, Any]] = payload.get("diagnostics") or []
        for diag in diagnostics:
            text = _diagnostic(diag)
            if diag.get("severity") == "error":
                errors.append(text)
            else:
                logging.warning("terraform-config-inspect: %s", text)
        if errors:
            raise ConfigInspectionError(
                "The Terraform configuration has errors: " + "; ".join(errors), 422
            )
        if result.returncode != 0:
            raise ConfigInspectionError(
                f"{self.__binary} exited with code {result.returncode}", 500
            )
        return payload


def _is_module(directory: Path) -> bool:
    return directory.is_dir() and any(
        p.is_file() and p.name.endswith(_MODULE_SUFFIXES) for p in directory.iterdir()
    )


def _parse_providers(data: dict[str, Any] | None) -> tuple[ProviderRequirement, ...]:
    providers: list[ProviderRequirement] = []
    for name, raw in (data or {}).items():
        body: dict[str, Any] = raw or {}
        # No source means the provider's implied hashicorp/<name> address.
        source = str(body.get("source") or f"hashicorp/{name}").lower()
        for registry in _DEFAULT_REGISTRIES:
            source = source.removeprefix(registry)
        constraints: list[Any] = body.get("version_constraints") or []
        providers.append(
            ProviderRequirement(
                name=name,
                source=source,
                version_constraints=tuple(sorted(str(c) for c in constraints)),
            )
        )
    return tuple(sorted(providers, key=lambda p: p.name))


def _parse_variables(data: dict[str, Any] | None) -> tuple[VariableSpec, ...]:
    return tuple(
        VariableSpec(
            name=name,
            type=_normalize_type(body.get("type")),
            required=bool(body.get("required")),
            sensitive=bool(body.get("sensitive")),
            description=str(body.get("description") or "").strip(),
        )
        for name, body in sorted((data or {}).items())
    )


def _normalize_type(type_expr: str | None) -> str | None:
    """The type expression on one line with single spaces.

    Reformatting a multi-line ``object({...})`` must not read as a
    requirement change (the type is part of the fingerprint).
    """
    return " ".join(type_expr.split()) if type_expr else None


def _diagnostic(diag: dict[str, Any]) -> str:
    pos = diag.get("pos") or {}
    where = f"{pos.get('filename')}:{pos.get('line')}: " if pos.get("filename") else ""
    detail = f" ({diag['detail']})" if diag.get("detail") else ""
    return f"{where}{diag.get('summary', 'unknown problem')}{detail}"


def _scan_var_files(directory: Path) -> tuple[VarFile, ...]:
    """Variable-definition files of the module at ``directory``.

    Auto-loaded files only count at the module's top level, as Terraform
    reads them. Optional ones are also looked for in subdirectories that
    are not modules themselves (``envs/``), skipping hidden directories
    such as ``.terraform`` and symlinks, which may point out of the clone.
    """
    found: list[VarFile] = []
    for current, dirnames, filenames in os.walk(directory):
        here = Path(current)
        depth = len(here.relative_to(directory).parts)
        dirnames[:] = (
            []
            if depth >= _MAX_VAR_FILE_DEPTH
            else sorted(
                d
                for d in dirnames
                if not d.startswith(".")
                and not (here / d).is_symlink()
                and not _is_module(here / d)
            )
        )
        for filename in sorted(filenames):
            path = here / filename
            if not filename.endswith(_VAR_FILE_SUFFIXES) or path.is_symlink():
                continue
            auto = depth == 0 and (
                filename in _AUTO_VAR_FILES or filename.endswith(_AUTO_VAR_SUFFIXES)
            )
            found.append(
                VarFile(
                    path=path.relative_to(directory).as_posix(),
                    auto=auto,
                    assigns=_assigned_names(path, auto),
                )
            )
    return tuple(found)


# Only the assigned names are read: Terraform reads the values itself.
# No comments, so no metadata keys mix with the variable names.
_NAMES_ONLY = hcl2.SerializationOptions(with_comments=False)


def _read_assignments(path: Path) -> dict[str, Any]:
    """The assignments of the variables file at ``path``, by variable name.

    Names come back as written; values keep python-hcl2's spelling, which
    is not Terraform's (strings stay quoted, expressions unevaluated).

    Raises:
        ValueError: When the file is not a set of assignments.
        OSError: When it cannot be read.
    """
    text = path.read_text(encoding="utf-8")
    data: Any
    if path.name.endswith(".json"):
        data = json.loads(text)
    else:
        data = hcl2.loads(text, serialization_options=_NAMES_ONLY)
    if not isinstance(data, dict):
        raise ValueError("the top level is not a set of assignments")
    return cast(dict[str, Any], data)


def _assigned_names(path: Path, auto: bool) -> frozenset[str]:
    """Names of the variables ``path`` sets.

    An unreadable auto-loaded file is an error, as it would break every
    Terraform run. An unreadable optional one is only logged and treated
    as setting nothing, so it cannot block a module that does not use it.
    """
    try:
        return frozenset(_read_assignments(path))
    except Exception as e:
        if auto:
            raise ConfigInspectionError(
                f"Cannot read variables file {path.name}: {e}", 422
            ) from e
        logging.warning("Ignoring unreadable variables file %s: %s", path, e)
        return frozenset()
