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
    _TF_VAR_SUFFIX: str = "TF_VAR_"

    def __init__(self, config_path: Path):
        self.__config_path: Path = config_path

    def create(
        self,
        fingerprint: str,
        variables: list[dict[str, str]],
        providers: list[dict[str, str | dict[str, str]]],
    ) -> Manifest:
        return self._write(
            {
                "version": self._VERSION,
                "fingerprint": fingerprint,
                "providers": providers,
                "variables": variables,
            }
        )

    def write_backend(self, config: str, lineage: str) -> Manifest:
        manifest: Manifest = self.load()
        dmanifest = asdict(manifest) | {
            "backend": {"config": config, "lineage": lineage}
        }
        return self._write(dmanifest)

    def write_variables(self, variables: dict[str, str]) -> Manifest:
        """Merges and overrides existing values"""
        manifest: Manifest = self.load()
        dmanifest = asdict(manifest)
        _ = self._parse(dmanifest)
        manifest_vars: list[dict[str, str]] | None = dmanifest.get("variables")

        dmanifest = dmanifest | {
            "variables": self._update_variables(variables, manifest_vars)
        }

        return self._write(dmanifest)

    def write_provider(
        self,
        provider: str,
        version: str,
        environment: dict[str, str],
    ) -> Manifest:
        """Merges and overrides existing values"""
        manifest: Manifest = self.load()
        dmanifest = asdict(manifest)
        _ = self._parse(dmanifest)
        if dmanifest.get("providers") is None:
            dmanifest = dmanifest | {
                "providers": [{"name": provider, "version": version}]
            }

        for prv in dmanifest["providers"]:
            if prv["name"] == provider:
                prv["environment"] = self._update_variables(
                    environment, prv.get("environment")
                )

        return self._write(dmanifest)

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

    def _parse_backend(self, data: dict[str, str] | None) -> Backend | None:
        if data is None:
            return None
        try:
            return Backend(config=data["config"], lineage=data["lineage"])
        except KeyError:
            logging.error(f"Manifest backend parse data fail. data={data}")
            raise ManifestReadError(
                message="Manifest backend parse data fail.",
                error_code=500,
            )

    def _parse_variables(
        self, data: list[dict[str, str]], prefix: str | None = None
    ) -> tuple[Variable, ...]:
        payload: list[Variable] = []
        try:
            for var in data:
                name = var["name"]
                value = var.get("value")
                if prefix and not name.startswith(prefix):
                    name = prefix + name
                payload.append(Variable(name=name, value=value))
            return tuple(payload)

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
            variables=self._parse_variables(variables, prefix=self._TF_VAR_SUFFIX),
            fingerprint=fingerprint,
        )

    def _update_variables(
        self, new: dict[str, str], to_update: list[dict[str, str]] | None = None
    ) -> list[dict[str, str]]:
        if to_update is not None:
            for v in to_update:
                new[v["name"]] = v["value"]
        return [{"name": n, "value": v} for n, v in new.items()]

    def _write(self, data: dict[str, Any]) -> Manifest:
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


if __name__ == "__main__":
    # import json

    handler = ManifestFile(Path("./manifest.yml"))
    # with open("./example-kumoss.yml", "r") as f:
    #     data = yaml.safe_load(f)
    #     print(json.dumps(data, indent=2))
    #     print(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    # data = asdict(manifest.load())
    # print(data)
    manifest = handler.create(
        fingerprint="sha256:qwerty",
        providers=[
            {
                "name": "azurerm",
                "version": "4.33.0",
                "environment": [
                    {"name": "ARM_SUBSCRIPTION_ID", "value": "22222-22222-22222-2222"}
                ],
            },
            {
                "name": "aws",
                "version": "6.72.0",
                "environment": ({"name": "AWS_REGION", "value": None},),
            },
        ],
        variables=[
            {
                "name": "sub_prod_id",
                "value": "11111111-1111-1111-1111-111111111111",
            },
            {
                "name": "ad_data_devops_owners",
                "value": [
                    "eaed4141-131d-4e88-8e9f-7d23422f6d1e",
                    "bbbb5c12-6105-47ae-ab59-f53cf9f74515",
                ],
            },
        ],
    )
    print(manifest)
