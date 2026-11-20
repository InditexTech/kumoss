# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self, TypeVar

from attrs import define as _attrs_define

T = TypeVar("T", bound="ResolveRequest")


@_attrs_define
class ResolveRequest:
    """
    Attributes:
        identifier (str): Business identifier to resolve. Free-form by design — could be
            a project name, a subscription code, a product slug, a full
            repo URL, or anything else the implementation accepts. The
            core's disabled-mode passthrough treats it as the repo URL
            directly.
    """

    identifier: str

    def to_dict(self) -> dict[str, Any]:
        identifier = self.identifier

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "identifier": identifier,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        identifier = d.pop("identifier")

        resolve_request = cls(
            identifier=identifier,
        )

        return resolve_request
