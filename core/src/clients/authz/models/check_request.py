# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="CheckRequest")


@_attrs_define
class CheckRequest:
    """
    Attributes:
        cloud (str):
        project (str):
        user_id (None | str | Unset): User to check. May be null for anonymous flows.
        environment (None | str | Unset):
    """

    cloud: str
    project: str
    user_id: None | str | Unset = UNSET
    environment: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        cloud = self.cloud

        project = self.project

        user_id: None | str | Unset
        if isinstance(self.user_id, Unset):
            user_id = UNSET
        else:
            user_id = self.user_id

        environment: None | str | Unset
        if isinstance(self.environment, Unset):
            environment = UNSET
        else:
            environment = self.environment

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "cloud": cloud,
                "project": project,
            }
        )
        if user_id is not UNSET:
            field_dict["user_id"] = user_id
        if environment is not UNSET:
            field_dict["environment"] = environment

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        cloud = d.pop("cloud")

        project = d.pop("project")

        def _parse_user_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        user_id = _parse_user_id(d.pop("user_id", UNSET))

        def _parse_environment(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        environment = _parse_environment(d.pop("environment", UNSET))

        check_request = cls(
            cloud=cloud,
            project=project,
            user_id=user_id,
            environment=environment,
        )

        return check_request
