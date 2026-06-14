# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="ResolveResponse")


@_attrs_define
class ResolveResponse:
    """
    Attributes:
        repo_url (str): URL Nebula should clone. Free-form because git accepts many
            URL shapes (https://, ssh+git://, git@host:path, file://,
            absolute paths). Implementations are responsible for returning
            something the deployment's git client can clone.
        project (str): Canonical project name used for downstream context (cloud
            resource group naming, tracer attributes, audit logs).
            Identity reference impl returns the input identifier; smarter
            implementations return the catalogue's canonical name.
        branch (None | str | Unset): Default branch Nebula should target. Implementations MAY omit
            this or send null; callers fall back to the resolved repo's
            default branch.
        path (None | str | Unset): Optional sub-path within the repo where the IaC lives. Useful
            for monorepos that host multiple IaC projects. May be omitted
            or sent as null.
    """

    repo_url: str
    project: str
    branch: None | str | Unset = UNSET
    path: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        repo_url = self.repo_url

        project = self.project

        branch: None | str | Unset
        if isinstance(self.branch, Unset):
            branch = UNSET
        else:
            branch = self.branch

        path: None | str | Unset
        if isinstance(self.path, Unset):
            path = UNSET
        else:
            path = self.path

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "repo_url": repo_url,
                "project": project,
            }
        )
        if branch is not UNSET:
            field_dict["branch"] = branch
        if path is not UNSET:
            field_dict["path"] = path

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        repo_url = d.pop("repo_url")

        project = d.pop("project")

        def _parse_branch(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        branch = _parse_branch(d.pop("branch", UNSET))

        def _parse_path(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        path = _parse_path(d.pop("path", UNSET))

        resolve_response = cls(
            repo_url=repo_url,
            project=project,
            branch=branch,
            path=path,
        )

        return resolve_response
