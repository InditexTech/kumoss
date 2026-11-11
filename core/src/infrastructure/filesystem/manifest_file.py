# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from src.application.exceptions import ManifestReadError
from src.domains.value_objects import Manifest
from src.domains.value_objects.manifest import (
    Backend,
    Provider,
    Variable,
)
from src.shared.logger import logging


class ManifestFile:
    """Reads the providers manifest of a root module from disk."""

    _VERSION: str = "1"

    def __init__(self, config_path: Path):
        self.__config_path: Path = config_path

    def create(
        self,
        fingerprint: str,
        variables: dict[str, str],
        providers: dict[str, str | dict[str, str]],
    ) -> Manifest:
        return self.write(
            {"version": self._VERSION, "fingerprint": fingerprint}
            | variables  # it may be empty
            | providers
        )

    def write(self, data: dict[str, Any]) -> Manifest:
        manifest = self._parse(data)
        with open(self.__config_path, "wb") as f:
            _ = f.write(
                yaml.safe_dump(
                    asdict(manifest),
                    encoding="utf8",
                    allow_unicode=True,
                    sort_keys=False,
                )
            )
        return manifest

    def write_backend(self, config: str, lineage: str) -> Manifest:
        manifest: Manifest = self.load()
        payload = asdict(manifest) | {"backend": {"config": config, "lineage": lineage}}
        return self.write(payload)

    def write_variables(self, variables: list[dict[str, str]]) -> Manifest:
        """Merges and overrides existing values"""
        manifest: Manifest = self.load()
        dict_manifest = asdict(manifest)
        _ = self._parse(dict_manifest)
        variables: list[dict[str, str]] | None = dict_manifest.get("variables")
        if variables:
            pass

        payload = asdict(manifest) | {
            "variables": [{"name": n, "value": v} for n, v in variables]
        }
        return self.write(payload)

    def load(self) -> Manifest:
        if not self.__config_path.exists():
            raise ManifestReadError(
                message=f"Manifest files doesn't exist at {self.__config_path}",
                error_code=500,
            )
        try:
            with open(self.__config_path, "r") as f:
                return self._parse(yaml.safe_load(f))
        except Exception as e:
            logging.error(f"Error reading manifest: {e}")
            raise ManifestReadError(
                message=f"Manifest parse error. Supported manifest version {self._VERSION}",
                error_code=500,
            )

    def _parse_backend(self, data: dict[str, str]) -> Backend:
        try:
            return Backend(config=data["config"], lineage=data["lineage"])
        except KeyError:
            logging.error(f"Manifest backend parse data fail. data={data}")
            raise ManifestReadError(
                message="Manifest backend parse data fail.",
                error_code=500,
            )

    def _parse_variables(self, data: list[dict[str, str]]) -> tuple[Variable, ...]:
        try:
            return tuple(
                Variable(name=var["name"], value=var.get("value")) for var in data
            )
        except KeyError:
            logging.error(f"Manifest Variables parse data fail. data={data}")
            raise ManifestReadError(
                message="Manifest Variables parse data fail.",
                error_code=500,
            )

    def _parse_providers(
        self,
        data: list[dict[str, str | dict[str, str]]],
    ) -> tuple[Provider, ...]:
        try:
            return tuple(
                Provider(
                    name=str(p["name"]),
                    version=str(p["version"]),
                    environment=self._parse_variables(p.get("environment", [])),
                )
                for p in data
            )
        except KeyError:
            logging.error(f"Manifest Providers parse data fail. data={data}")
            raise ManifestReadError(
                message="Manifest Providers parse data fail.",
                error_code=500,
            )

    def _parse(self, data: dict[str, Any]) -> Manifest:
        version = data["version"]
        backend = data.get("backend")
        providers = data.get("providers", ())
        variables = data.get("variables", ())
        fingerprint = data["fingerprint"]
        return Manifest(
            version=version,
            backend=self._parse_backend(backend),
            providers=self._parse_providers(providers),
            variables=self._parse_variables(variables),
            fingerprint=fingerprint,
        )


if __name__ == "__main__":
    # import json

    manifest = ManifestFile(Path("./manifest.yml"))
    # with open("./example-kumoss.yml", "r") as f:
    #     data = yaml.safe_load(f)
    #     print(json.dumps(data, indent=2))
    #     print(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    data = asdict(manifest.load())
    print(data)
    _ = manifest.write(data)
