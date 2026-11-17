# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Self, TypeVar

from attrs import define as _attrs_define

from ..models.action_name import ActionName
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.action_properties import ActionProperties


T = TypeVar("T", bound="Action")


@_attrs_define
class Action:
    """
    Attributes:
        name (ActionName):
        properties (ActionProperties | Unset):
    """

    name: ActionName
    properties: ActionProperties | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        name = self.name.value

        properties: dict[str, Any] | Unset = UNSET
        if not isinstance(self.properties, Unset):
            properties = self.properties.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "name": name,
            }
        )
        if properties is not UNSET:
            field_dict["properties"] = properties

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.action_properties import ActionProperties

        d = dict(src_dict)
        name = ActionName(d.pop("name"))

        _properties = d.pop("properties", UNSET)
        properties: ActionProperties | Unset
        if isinstance(_properties, Unset):
            properties = UNSET
        else:
            properties = ActionProperties.from_dict(_properties)

        action = cls(
            name=name,
            properties=properties,
        )

        return action
