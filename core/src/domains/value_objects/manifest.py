# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Backend:
    # https://developer.hashicorp.com/terraform/language/backend
    type: Literal["kumoss", "local", "azurerm", "s3", "gcs", "oci", "pg"]


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
    backend: Backend
    providers: tuple[Provider, ...] = ()
    variables: tuple[Variable, ...] = ()
