from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.resource_properties_provider import ResourcePropertiesProvider
from ..types import UNSET, Unset

T = TypeVar("T", bound="ResourceProperties")


@_attrs_define
class ResourceProperties:
    """
    Attributes:
        provider (ResourcePropertiesProvider | Unset):
        repo_uri (str | Unset):
        iac_path (str | Unset):
    """

    provider: ResourcePropertiesProvider | Unset = UNSET
    repo_uri: str | Unset = UNSET
    iac_path: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        provider: str | Unset = UNSET
        if not isinstance(self.provider, Unset):
            provider = self.provider.value

        repo_uri = self.repo_uri

        iac_path = self.iac_path

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if provider is not UNSET:
            field_dict["provider"] = provider
        if repo_uri is not UNSET:
            field_dict["repo_uri"] = repo_uri
        if iac_path is not UNSET:
            field_dict["iac_path"] = iac_path

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        _provider = d.pop("provider", UNSET)
        provider: ResourcePropertiesProvider | Unset
        if isinstance(_provider, Unset):
            provider = UNSET
        else:
            provider = ResourcePropertiesProvider(_provider)

        repo_uri = d.pop("repo_uri", UNSET)

        iac_path = d.pop("iac_path", UNSET)

        resource_properties = cls(
            provider=provider,
            repo_uri=repo_uri,
            iac_path=iac_path,
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
