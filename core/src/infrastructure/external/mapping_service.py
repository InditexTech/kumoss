# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Mapping microservice client used by core.

Wraps the generated `src.clients.mapping` HTTP client behind a small,
async-friendly facade. Mirrors the pattern used by
`AuthzServiceClient`: read endpoint+token from system_config,
construct a fresh `AuthenticatedClient` per call, and degrade
gracefully to the OSS-default identity passthrough when the service
is disabled or unconfigured.

Surface:

- `MappingServiceClient.resolve(identifier, cloud, environment)` →
  `ResolvedRef(repo_url, project, branch, path)`. Returns identity
  passthrough when mapping is disabled so existing callers keep working.
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
from src.shared.exceptions import ExceptionHandler


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


def _unwrap(value: str | None | Unset) -> str | None:
    return None if isinstance(value, Unset) else value


class MappingServiceClient:
    """Call the mapping microservice via the generated HTTP client."""

    async def resolve(
        self,
        identifier: str,
        *,
        cloud: str | None = None,
        environment: str | None = None,
    ) -> ResolvedRef:
        """Resolve `identifier` via the mapping service, or identity-pass it.

        Raises `ExceptionHandler` if the mapping service is enabled but the
        call fails (timeout, unreachable, bad status) or returns an
        unexpected response — callers should treat that as a fatal request
        error, not silently fall back to identity (which would mask
        misconfiguration). 504 for timeouts, 502 otherwise.
        """
        cfg = system_config.services.mapping
        if not cfg.enabled or not cfg.endpoint:
            return ResolvedRef(repo_url=identifier, project=identifier)

        body = ResolveRequest(
            identifier=identifier,
            cloud=cloud if cloud is not None else UNSET,
            environment=environment if environment is not None else UNSET,
        )
        client = AuthenticatedClient(
            base_url=cfg.endpoint,
            token=cfg.token,
            timeout=httpx.Timeout(10.0),
        )
        try:
            async with client as c:
                response = await resolve_op.asyncio(client=c, body=body)
        except httpx.TimeoutException as e:
            raise ExceptionHandler(f"mapping service timed out: {e}", 504) from e
        except httpx.RequestError as e:
            raise ExceptionHandler(f"mapping service unreachable: {e}", 502) from e
        if not isinstance(response, ResolveResponse):
            raise ExceptionHandler(
                f"mapping service returned an unexpected response: {response!r}", 502
            )
        return ResolvedRef(
            repo_url=response.repo_url,
            project=response.project,
            branch=_unwrap(response.branch),
            path=_unwrap(response.path),
        )
