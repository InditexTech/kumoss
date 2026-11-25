# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Self, TypeVar

from attrs import define as _attrs_define

from ..models.resource_type import ResourceType
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.resource_properties import ResourceProperties


T = TypeVar("T", bound="Resource")


@_attrs_define
class Resource:
    """
    Attributes:
        type_ (ResourceType):
        id (str):
        properties (ResourceProperties | Unset):
    """

    type_: ResourceType
    id: str
    properties: ResourceProperties | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        type_ = self.type_.value

        id = self.id

        properties: dict[str, Any] | Unset = UNSET
        if not isinstance(self.properties, Unset):
            properties = self.properties.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "type": type_,
                "id": id,
            }
        )
        if properties is not UNSET:
            field_dict["properties"] = properties

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.resource_properties import ResourceProperties

        d = dict(src_dict)
        type_ = ResourceType(d.pop("type"))

        id = d.pop("id")

        _properties = d.pop("properties", UNSET)
        properties: ResourceProperties | Unset
        if isinstance(_properties, Unset):
            properties = UNSET
        else:
            properties = ResourceProperties.from_dict(_properties)

        resource = cls(
            type_=type_,
            id=id,
            properties=properties,
        )

        return resource
