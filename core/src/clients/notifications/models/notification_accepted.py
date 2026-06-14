# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar
from uuid import UUID

from attrs import define as _attrs_define

T = TypeVar("T", bound="NotificationAccepted")


@_attrs_define
class NotificationAccepted:
    """
    Attributes:
        delivery_id (UUID): Implementation-assigned identifier for this delivery attempt.
    """

    delivery_id: UUID

    def to_dict(self) -> dict[str, Any]:
        delivery_id = str(self.delivery_id)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "delivery_id": delivery_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        delivery_id = UUID(d.pop("delivery_id"))

        notification_accepted = cls(
            delivery_id=delivery_id,
        )

        return notification_accepted
