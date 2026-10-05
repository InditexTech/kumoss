# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self, TypeVar, cast

from attrs import define as _attrs_define

from ..models.terraform_provider import TerraformProvider
from ..types import UNSET, Unset

T = TypeVar("T", bound="ResolveResponse")


@_attrs_define
class ResolveResponse:
    """
    Attributes:
        repo_url (str): HTTPS URL Kumoss should clone. Must use the `https://` scheme
            (case-insensitive) and name a host: Kumoss clones, pushes and
            opens pull requests over HTTPS only, and rejects SSH,
            `git://`, `http://`, `file://` and local paths. When the
            identifier already is an `https://` repository URL,
            implementations pass it through unchanged; an identifier
            that cannot be mapped to one answers `404`.
        identifier (str): The request's `identifier`, echoed verbatim. Normative rather
            than conventional: callers correlate responses on it.
        terraform_provider (None | TerraformProvider | Unset): Provider the deployment targets. Echoes the request's
            value
            when one was sent; otherwise the implementation's best-effort
            answer, or `null` for "I do not know, ask the user". Never
            guess — the caller skips its provider prompt when this is
            non-null, so a wrong value is never seen or corrected.
        scope_id (None | str | Unset): Cloud scope the deployment targets — Azure: subscription id,
            GCP: project id, AWS: account id, OCI: compartment OCID — as
            a best-effort answer, or `null` for "I do not know, ask the
            user". Same warning as `terraform_provider`: the caller skips
            its scope prompt when this is non-null, so a wrong value
            sends the user into a plan against the wrong scope with
            nothing to catch it.
    """

    repo_url: str
    identifier: str
    terraform_provider: None | TerraformProvider | Unset = UNSET
    scope_id: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        repo_url = self.repo_url

        identifier = self.identifier

        terraform_provider: None | str | Unset
        if isinstance(self.terraform_provider, Unset):
            terraform_provider = UNSET
        elif isinstance(self.terraform_provider, TerraformProvider):
            terraform_provider = self.terraform_provider.value
        else:
            terraform_provider = self.terraform_provider

        scope_id: None | str | Unset
        if isinstance(self.scope_id, Unset):
            scope_id = UNSET
        else:
            scope_id = self.scope_id

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "repo_url": repo_url,
                "identifier": identifier,
            }
        )
        if terraform_provider is not UNSET:
            field_dict["terraform_provider"] = terraform_provider
        if scope_id is not UNSET:
            field_dict["scope_id"] = scope_id

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        repo_url = d.pop("repo_url")

        identifier = d.pop("identifier")

        def _parse_terraform_provider(data: object) -> None | TerraformProvider | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                terraform_provider_type_0 = TerraformProvider(data)

                return terraform_provider_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | TerraformProvider | Unset, data)

        terraform_provider = _parse_terraform_provider(
            d.pop("terraform_provider", UNSET)
        )

        def _parse_scope_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        scope_id = _parse_scope_id(d.pop("scope_id", UNSET))

        resolve_response = cls(
            repo_url=repo_url,
            identifier=identifier,
            terraform_provider=terraform_provider,
            scope_id=scope_id,
        )

        return resolve_response
