# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass


@dataclass(frozen=True)
class Backend:
    """Value object: the terraform backend declared in the manifest."""

    config: str
    lineage: str


@dataclass(frozen=True)
class Fingerprint:
    """Value object: the checksum of the manifest and when it was last validated."""

    checksum: str
    validated_at: str


@dataclass(frozen=True)
class Provider:
    """Value object: one terraform provider pinned by the manifest."""

    name: str
    version: str


@dataclass(frozen=True)
class ProviderEnv:
    """Value object: one env var needed by the providers."""

    name: str
    value: str


@dataclass(frozen=True)
class Manifest:
    """Value object: the parsed providers manifest of a root module.

    ``providers`` the terraform providers the manifest pins.
    ``provider_env`` environment variables exposed to those providers.
    """

    version: str
    backend: Backend
    fingerprint: Fingerprint
    providers: tuple[Provider, ...] = ()
    provider_env: tuple[ProviderEnv, ...] = ()
