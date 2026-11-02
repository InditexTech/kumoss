from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Self, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.response_context_reason_admin import ResponseContextReasonAdmin
    from ..models.response_context_reason_user import ResponseContextReasonUser


T = TypeVar("T", bound="ResponseContext")


@_attrs_define
class ResponseContext:
    """
    Attributes:
        reason_user (ResponseContextReasonUser | Unset):
        reason_admin (ResponseContextReasonAdmin | Unset):
    """

    reason_user: ResponseContextReasonUser | Unset = UNSET
    reason_admin: ResponseContextReasonAdmin | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        reason_user: dict[str, Any] | Unset = UNSET
        if not isinstance(self.reason_user, Unset):
            reason_user = self.reason_user.to_dict()

        reason_admin: dict[str, Any] | Unset = UNSET
        if not isinstance(self.reason_admin, Unset):
            reason_admin = self.reason_admin.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if reason_user is not UNSET:
            field_dict["reason_user"] = reason_user
        if reason_admin is not UNSET:
            field_dict["reason_admin"] = reason_admin

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.response_context_reason_admin import (
            ResponseContextReasonAdmin,
        )
        from ..models.response_context_reason_user import (
            ResponseContextReasonUser,
        )

        d = dict(src_dict)
        _reason_user = d.pop("reason_user", UNSET)
        reason_user: ResponseContextReasonUser | Unset
        if isinstance(_reason_user, Unset):
            reason_user = UNSET
        else:
            reason_user = ResponseContextReasonUser.from_dict(_reason_user)

        _reason_admin = d.pop("reason_admin", UNSET)
        reason_admin: ResponseContextReasonAdmin | Unset
        if isinstance(_reason_admin, Unset):
            reason_admin = UNSET
        else:
            reason_admin = ResponseContextReasonAdmin.from_dict(_reason_admin)

        response_context = cls(
            reason_user=reason_user,
            reason_admin=reason_admin,
        )

        response_context.additional_properties = d
        return response_context

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
