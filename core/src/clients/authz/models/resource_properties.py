# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="ResourceProperties")


@_attrs_define
class ResourceProperties:
    """
    Attributes:
        provider (str | Unset): Terraform provider type name the scope belongs to (the last
            segment of its source address, e.g. `azurerm`, `google`,
            `aws`, `oci`). Any provider a root module uses may appear.
            Changed in 2.0.0 from a fixed enum of the core's former names
            (`azure`, `gcp`, `vmware`...). The core evaluates one request
            per provider scope of the session's root module; a module with
            no scoped provider is evaluated once, with an empty resource
            id and no provider.
        repo_uri (str | Unset):
        root_module_path (str | Unset):
    """

    provider: str | Unset = UNSET
    repo_uri: str | Unset = UNSET
    root_module_path: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        provider = self.provider

        repo_uri = self.repo_uri

        root_module_path = self.root_module_path

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if provider is not UNSET:
            field_dict["provider"] = provider
        if repo_uri is not UNSET:
            field_dict["repo_uri"] = repo_uri
        if root_module_path is not UNSET:
            field_dict["root_module_path"] = root_module_path

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        provider = d.pop("provider", UNSET)

        repo_uri = d.pop("repo_uri", UNSET)

        root_module_path = d.pop("root_module_path", UNSET)

        resource_properties = cls(
            provider=provider,
            repo_uri=repo_uri,
            root_module_path=root_module_path,
        )

        resource_properties.additional_properties = d
        return resource_properties

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
