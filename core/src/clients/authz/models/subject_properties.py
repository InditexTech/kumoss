from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="SubjectProperties")


@_attrs_define
class SubjectProperties:
    """
    Attributes:
        issuer (str | Unset):
        email (str | Unset):
        groups (list[str] | Unset):
    """

    issuer: str | Unset = UNSET
    email: str | Unset = UNSET
    groups: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        issuer = self.issuer

        email = self.email

        groups: list[str] | Unset = UNSET
        if not isinstance(self.groups, Unset):
            groups = self.groups

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if issuer is not UNSET:
            field_dict["issuer"] = issuer
        if email is not UNSET:
            field_dict["email"] = email
        if groups is not UNSET:
            field_dict["groups"] = groups

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        issuer = d.pop("issuer", UNSET)

        email = d.pop("email", UNSET)

        groups = cast(list[str], d.pop("groups", UNSET))

        subject_properties = cls(
            issuer=issuer,
            email=email,
            groups=groups,
        )

        subject_properties.additional_properties = d
        return subject_properties

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
