# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self, TypeVar, cast

from attrs import define as _attrs_define

from ..models.terraform_provider import TerraformProvider
from ..types import UNSET, Unset

T = TypeVar("T", bound="ResolveRequest")


@_attrs_define
class ResolveRequest:
    """
    Attributes:
        identifier (str): Business identifier to resolve. Free-form by design — could be
            a project name, a subscription code, a product slug, a full
            repo URL, or anything else the implementation accepts. The
            identity reference impl treats this as the repo URL directly.
        terraform_provider (None | TerraformProvider | Unset): Provider the caller already knows the deployment targets.
            Implementations MAY use it to disambiguate identifiers that
            span clouds, and MUST echo it back in the response when it is
            sent. May be omitted or sent as null, which means the caller
            does not know either.
    """

    identifier: str
    terraform_provider: None | TerraformProvider | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        identifier = self.identifier

        terraform_provider: None | str | Unset
        if isinstance(self.terraform_provider, Unset):
            terraform_provider = UNSET
        elif isinstance(self.terraform_provider, TerraformProvider):
            terraform_provider = self.terraform_provider.value
        else:
            terraform_provider = self.terraform_provider

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "identifier": identifier,
            }
        )
        if terraform_provider is not UNSET:
            field_dict["terraform_provider"] = terraform_provider

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        identifier = d.pop("identifier")

        def _parse_terraform_provider(data: object) -> None | TerraformProvider | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                terraform_provider_type_0 = TerraformProvider(data)

                return terraform_provider_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | TerraformProvider | Unset, data)

        terraform_provider = _parse_terraform_provider(
            d.pop("terraform_provider", UNSET)
        )

        resolve_request = cls(
            identifier=identifier,
            terraform_provider=terraform_provider,
        )

        return resolve_request
