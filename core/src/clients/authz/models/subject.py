from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.subject_type import SubjectType
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.subject_properties import SubjectProperties


T = TypeVar("T", bound="Subject")


@_attrs_define
class Subject:
    """
    Attributes:
        type_ (SubjectType):
        id (str):
        properties (SubjectProperties | Unset):
    """

    type_: SubjectType
    id: str
    properties: SubjectProperties | Unset = UNSET

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
        from ..models.subject_properties import SubjectProperties

        d = dict(src_dict)
        type_ = SubjectType(d.pop("type"))

        id = d.pop("id")

        _properties = d.pop("properties", UNSET)
        properties: SubjectProperties | Unset
        if isinstance(_properties, Unset):
            properties = UNSET
        else:
            properties = SubjectProperties.from_dict(_properties)

        subject = cls(
            type_=type_,
            id=id,
            properties=properties,
        )

        return subject
