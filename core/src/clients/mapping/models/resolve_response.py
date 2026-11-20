# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self, TypeVar

from attrs import define as _attrs_define

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
    """

    repo_url: str
    identifier: str

    def to_dict(self) -> dict[str, Any]:
        repo_url = self.repo_url

        identifier = self.identifier

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "repo_url": repo_url,
                "identifier": identifier,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        repo_url = d.pop("repo_url")

        identifier = d.pop("identifier")

        resolve_response = cls(
            repo_url=repo_url,
            identifier=identifier,
        )

        return resolve_response
