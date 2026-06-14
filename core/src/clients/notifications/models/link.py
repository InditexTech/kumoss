# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

T = TypeVar("T", bound="Link")


@_attrs_define
class Link:
    """
    Attributes:
        label (str):
        url (str):
    """

    label: str
    url: str

    def to_dict(self) -> dict[str, Any]:
        label = self.label

        url = self.url

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "label": label,
                "url": url,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        label = d.pop("label")

        url = d.pop("url")

        link = cls(
            label=label,
            url=url,
        )

        return link
