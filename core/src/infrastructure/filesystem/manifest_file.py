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
    Fingerprint,
    Provider,
    Variable,
)
from src.shared.logger import logging


class ManifestFile:
    """Reads the providers manifest of a root module from disk."""

    _VERSION: str = "1"

    def __init__(self, config: Path):
        self.__config: Path = config

    def initialize(
        self,
        config: str,
        lieage: str,
        providers: dict[str, str | dict[str, str]],
        variables: dict[str, str],
        fingerprint: str,
    ) -> None:
        pass

    def write(self, data: dict[str, Any] | None) -> Manifest:
        if data is None:
            return Manifest(
                version=self._VERSION,
                backend=Backend("", ""),
                fingerprint=Fingerprint("", ""),
            )
        manifest: Manifest = self._parse(data)
        with open("./kumoss.yaml", "wb") as f:
            _ = f.write(
                yaml.safe_dump(
                    asdict(manifest),
                    encoding="utf8",
                    allow_unicode=True,
                    sort_keys=False,
                )
            )
        return manifest

    def load(self) -> Manifest:
        if not self.__config.exists():
            return self.write(None)
        try:
            with open(self.__config, "r") as f:
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
            raise ManifestReadError(
                message=f"Manifest backend parse data fail. data={data}",
                error_code=500,
            )

    def _parse_variables(self, data: list[dict[str, str]]) -> tuple[Variable, ...]:
        try:
            return tuple(
                Variable(name=var["name"], value=var.get("value")) for var in data
            )
        except KeyError:
            raise ManifestReadError(
                message=f"Manifest Variables parse data fail. data={data}",
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
                    environment=self._parse_variables(p.get("variables", [])),
                )
                for p in data
            )
        except KeyError:
            raise ManifestReadError(
                message=f"Manifest Providers parse data fail. data={data}",
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
    import json

    manifest = ManifestFile(Path("./example-kumoss.yml"))
    with open("./example-kumoss.yml", "r") as f:
        data = yaml.safe_load(f)
        print(json.dumps(data, indent=2))
        print(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    # data = asdict(manifest.load())
    # _ = manifest.write(data)
