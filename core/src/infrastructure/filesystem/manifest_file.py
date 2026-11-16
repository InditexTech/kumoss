# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""The manifest as a YAML file committed inside the root module.

Layout (version 1)::

    version: "1"
    fingerprint: sha256:<hex>
    providers:
      - name: azurerm
        source: hashicorp/azurerm
        version_constraints: ["= 3.85.0"]
    var_files: [envs/dev.tfvars]
    variables:
      - name: region
        value: {location: westeurope}
      - name: db_password
        sensitive: true        # value kept in the secret store, never here

Reading is strict: anything off-layout is reported rather than guessed,
since the file is committed and may have been edited by hand.
"""

import os
import tempfile
from pathlib import Path
from typing import Any, final, override

import yaml

from src.domains.exceptions import ManifestReadError
from src.domains.interfaces.manifest_repository_interface import IManifestRepository
from src.domains.value_objects.manifest import Manifest, Variable
from src.domains.value_objects.terraform_requirements import ProviderRequirement
from src.shared.config import system_config

_VERSION = "1"
_HEADER = (
    "# Managed by Kumoss: the inputs this Terraform root module is configured with.\n"
    "# Sensitive values are never stored here, only their names.\n"
)
_TIMESTAMP_TAG = "tag:yaml.org,2002:timestamp"


class _Loader(yaml.SafeLoader):
    """Safe loader that keeps unquoted dates as strings, as Terraform would read them."""


_Loader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != _TIMESTAMP_TAG]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


@final
class ManifestFile(IManifestRepository):
    """``IManifestRepository`` storing the manifest as a file in the module's directory."""

    def __init__(self, filename: str | None = None):
        self.__filename = filename or system_config.paths.manifest_filename

    @override
    def load(self, directory: Path) -> Manifest | None:
        path = directory / self.__filename
        if not path.is_file():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.load(f, Loader=_Loader)
        except (OSError, yaml.YAMLError) as e:
            raise ManifestReadError(f"Cannot read {self.__filename}: {e}", 422) from e
        try:
            return _from_dict(data)
        except (TypeError, ValueError, KeyError) as e:
            raise ManifestReadError(f"Invalid {self.__filename}: {e}", 422) from e

    @override
    def save(self, directory: Path, manifest: Manifest) -> None:
        body = yaml.safe_dump(
            _to_dict(manifest),
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
        # Write next to the target and swap it in, so a reader never sees
        # half a file.
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=f".{self.__filename}.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                _ = f.write(_HEADER + body)
            os.chmod(tmp, 0o644)
            os.replace(tmp, directory / self.__filename)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def _to_dict(manifest: Manifest) -> dict[str, Any]:
    return {
        "version": _VERSION,
        "fingerprint": manifest.fingerprint,
        "providers": [
            {
                "name": p.name,
                "source": p.source,
                "version_constraints": list(p.version_constraints),
            }
            for p in manifest.providers
        ],
        "var_files": list(manifest.var_files),
        "variables": [
            {"name": v.name, "sensitive": True}
            if v.sensitive
            else {"name": v.name, "value": v.value}
            for v in manifest.variables
        ],
    }


def _from_dict(data: Any) -> Manifest:
    data = _mapping(data, "the document")
    version = str(data.get("version", ""))
    if version != _VERSION:
        raise ValueError(
            f"unsupported version {version or '(none)'!r}; this Kumoss reads version {_VERSION}"
        )
    fingerprint = data.get("fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise ValueError("'fingerprint' must be a non-empty string")

    providers: list[ProviderRequirement] = []
    for item in _list(data.get("providers"), "providers"):
        item = _mapping(item, "a provider")
        constraints = _list(item.get("version_constraints"), "version_constraints")
        providers.append(
            ProviderRequirement(
                name=_string(item, "name"),
                source=_string(item, "source"),
                version_constraints=tuple(str(c) for c in constraints),
            )
        )
    var_files = tuple(str(f) for f in _list(data.get("var_files"), "var_files"))

    variables: list[Variable] = []
    for item in _list(data.get("variables"), "variables"):
        item = _mapping(item, "a variable")
        name = _string(item, "name")
        if item.get("sensitive") is True and "value" in item:
            raise ValueError(
                f"variable {name!r} is sensitive and must not have a value in the file; "
                + "remove it and rotate the secret, it has been exposed"
            )
        variables.append(
            Variable(
                name=name,
                value=item.get("value"),
                sensitive=item.get("sensitive") is True,
            )
        )
    names = [v.name for v in variables]
    if len(set(names)) != len(names):
        raise ValueError("a variable is listed more than once")

    return Manifest(
        fingerprint=fingerprint,
        providers=tuple(providers),
        var_files=var_files,
        variables=tuple(variables),
    )


def _mapping(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{what} must be a mapping")
    return value


def _list(value: Any, what: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"'{what}' must be a list")
    return value


def _string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"'{key}' must be a non-empty string")
    return value
