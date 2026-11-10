# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from src.application.exceptions import ManifestReadError
from src.domains.value_objects import ManifestObject
from src.domains.value_objects.manifest_object import (
    Backend,
    Fingerprint,
    Provider,
    ProviderEnv,
)
from src.shared.logger import logging


class Manifest:
    """Reads the providers manifest of a root module from disk."""

    _VERSION: str = "1.1"

    def __init__(self, config: Path):
        self.__config: Path = config

    # TODO: pass optional arguments or create different methods (def add_env, def update_providers, etc)
    def write(self, data: dict[str, Any] | None) -> ManifestObject:
        if data is None:
            return ManifestObject(
                version=self._VERSION,
                backend=Backend("", ""),
                fingerprint=Fingerprint("", ""),
            )
        manifest: ManifestObject = self._parse(data)
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

    def load(self) -> ManifestObject:
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

    @staticmethod
    def _parse(data: dict[str, Any]) -> ManifestObject:
        # str() everywhere: YAML turns unquoted versions into numbers and timestamps into datetimes
        backend = data["backend"]
        fingerprint = data["fingerprint"]
        return ManifestObject(
            version=str(data["version"]),
            backend=Backend(
                config=str(backend["config"]), lineage=str(backend["lineage"])
            ),
            fingerprint=Fingerprint(
                checksum=str(fingerprint["checksum"]),
                validated_at=str(fingerprint["validated_at"]),
            ),
            providers=tuple(
                Provider(name=str(p["name"]), version=str(p["version"]))
                for p in data.get("providers") or ()
            ),
            provider_env=tuple(
                ProviderEnv(name=str(p["name"]), value=str(p["value"]))
                for p in data.get("provider_env") or ()
            ),
        )


if __name__ == "__main__":
    manifest = Manifest(Path("./test_kumoss.yaml"))
    data = asdict(manifest.load())
    print(data)
    manifest.write(data)
