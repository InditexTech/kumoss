# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Resolve a business identifier into an IaC repository reference.

Wraps the generated mapping client and applies the OSS-default identity
fallback when the mapping service is disabled in the system configuration.
Call sites should use this helper rather than importing the client
directly so that the disabled-service path is uniform.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from src.clients.mapping.api.resolve import resolve as resolve_op
from src.clients.mapping.client import AuthenticatedClient
from src.clients.mapping.models.resolve_request import ResolveRequest
from src.clients.mapping.models.resolve_response import ResolveResponse
from src.clients.mapping.types import UNSET, Unset
from src.shared.config import system_config


@dataclass(frozen=True)
class ResolvedRef:
    """Outcome of resolving an identifier.

    `repo_url` is what `git clone` should target; `project` is the canonical
    name to use for downstream context (auth, tracer, audit). When mapping
    is disabled, both echo the input identifier.
    """

    repo_url: str
    project: str
    branch: str | None = None
    path: str | None = None


def _build_client() -> AuthenticatedClient | None:
    cfg = system_config.services.mapping
    if not cfg.enabled or not cfg.endpoint:
        return None
    return AuthenticatedClient(
        base_url=cfg.endpoint,
        token=cfg.token,
        timeout=httpx.Timeout(10.0),
    )


async def resolve(
    identifier: str,
    *,
    cloud: str | None = None,
    environment: str | None = None,
) -> ResolvedRef:
    """Resolve `identifier` via the mapping service, or identity-pass it.

    Raises ValueError if the mapping service is enabled but the call fails
    or returns an unexpected response — callers should treat that as a
    fatal request error, not silently fall back to identity (which would
    mask misconfiguration).
    """
    client = _build_client()
    if client is None:
        return ResolvedRef(repo_url=identifier, project=identifier)

    body = ResolveRequest(
        identifier=identifier,
        cloud=cloud if cloud is not None else UNSET,
        environment=environment if environment is not None else UNSET,
    )
    async with client as c:
        response = await resolve_op.asyncio(client=c, body=body)
    if not isinstance(response, ResolveResponse):
        raise ValueError(
            f"Mapping service returned an unexpected response: {response!r}"
        )
    return ResolvedRef(
        repo_url=response.repo_url,
        project=response.project,
        branch=_unwrap(response.branch),
        path=_unwrap(response.path),
    )


def _unwrap(value: str | Unset) -> str | None:
    return None if isinstance(value, Unset) else value
