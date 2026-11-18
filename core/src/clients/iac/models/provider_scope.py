# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self, TypeVar

from attrs import define as _attrs_define

T = TypeVar("T", bound="ProviderScope")


@_attrs_define
class ProviderScope:
    """The scope one provider of the root module runs against (see
    "Scope injection").

        Attributes:
            provider (str): Terraform provider type name (the last segment of its
                source address, e.g. `azurerm` for `hashicorp/azurerm`).
                Any name is accepted; only `azurerm`, `google`, `aws` and
                `oci` have their scope injected.
            scope_id (str): Scope the provider's resources live in — `azurerm`:
                subscription id, `google`: project id, `aws`: account id,
                `oci`: compartment OCID.
    """

    provider: str
    scope_id: str

    def to_dict(self) -> dict[str, Any]:
        provider = self.provider

        scope_id = self.scope_id

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "provider": provider,
                "scope_id": scope_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        provider = d.pop("provider")

        scope_id = d.pop("scope_id")

        provider_scope = cls(
            provider=provider,
            scope_id=scope_id,
        )

        return provider_scope
