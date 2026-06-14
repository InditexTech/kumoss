# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="CheckResponse")


@_attrs_define
class CheckResponse:
    """
    Attributes:
        authorized (bool):
        portal_url (None | str | Unset): Implementation-supplied link to the cloud portal for the
            resource (Azure Portal, GCP Console). May be null when the
            implementation has no portal-URL convention.
        reason (None | str | Unset): Human-readable explanation of the decision. Useful for
            debugging and for surfacing in the UI.
    """

    authorized: bool
    portal_url: None | str | Unset = UNSET
    reason: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        authorized = self.authorized

        portal_url: None | str | Unset
        if isinstance(self.portal_url, Unset):
            portal_url = UNSET
        else:
            portal_url = self.portal_url

        reason: None | str | Unset
        if isinstance(self.reason, Unset):
            reason = UNSET
        else:
            reason = self.reason

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "authorized": authorized,
            }
        )
        if portal_url is not UNSET:
            field_dict["portal_url"] = portal_url
        if reason is not UNSET:
            field_dict["reason"] = reason

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        authorized = d.pop("authorized")

        def _parse_portal_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        portal_url = _parse_portal_url(d.pop("portal_url", UNSET))

        def _parse_reason(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        reason = _parse_reason(d.pop("reason", UNSET))

        check_response = cls(
            authorized=authorized,
            portal_url=portal_url,
            reason=reason,
        )

        return check_response
