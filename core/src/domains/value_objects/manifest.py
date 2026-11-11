# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass


@dataclass(frozen=True)
class Backend:
    config: str
    lineage: str


@dataclass(frozen=True)
class Provider:
    name: str
    version: str
    environment: tuple["Variable", ...] = ()


@dataclass(frozen=True)
class Variable:
    name: str
    value: str | None = None


@dataclass(frozen=True)
class Fingerprint:
    checksum: str


@dataclass(frozen=True)
class Manifest:
    version: str
    fingerprint: Fingerprint
    providers: tuple[Provider, ...] = ()
    variables: tuple[Variable, ...] = ()
    backend: Backend | None = None
