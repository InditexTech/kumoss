# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="ResolveRequest")


@_attrs_define
class ResolveRequest:
    """
    Attributes:
        identifier (str): Business identifier to resolve. Free-form by design — could be
            a project name, a subscription code, a product slug, a full
            repo URL, or anything else the implementation accepts. The
            identity reference impl treats this as the repo URL directly.
        cloud (None | str | Unset): Optional cloud hint (`azure`, `gcp`, `aws`, …). Implementations
            MAY use this to disambiguate identifiers that span clouds.
            May be omitted or sent as null.
        environment (None | str | Unset): Optional deployment-dimension hint (`dev`, `staging`, `pro`, …).
            Implementations MAY use this to route to environment-specific
            mirrors of the same logical repo. May be omitted or sent as null.
    """

    identifier: str
    cloud: None | str | Unset = UNSET
    environment: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        identifier = self.identifier

        cloud: None | str | Unset
        if isinstance(self.cloud, Unset):
            cloud = UNSET
        else:
            cloud = self.cloud

        environment: None | str | Unset
        if isinstance(self.environment, Unset):
            environment = UNSET
        else:
            environment = self.environment

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "identifier": identifier,
            }
        )
        if cloud is not UNSET:
            field_dict["cloud"] = cloud
        if environment is not UNSET:
            field_dict["environment"] = environment

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        identifier = d.pop("identifier")

        def _parse_cloud(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        cloud = _parse_cloud(d.pop("cloud", UNSET))

        def _parse_environment(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        environment = _parse_environment(d.pop("environment", UNSET))

        resolve_request = cls(
            identifier=identifier,
            cloud=cloud,
            environment=environment,
        )

        return resolve_request
