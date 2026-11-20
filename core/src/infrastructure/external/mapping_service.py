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

- `MappingServiceClient.resolve(identifier)` →
  `ResolvedRef(repo_url, identifier)`. Returns identity passthrough
  when mapping is disabled so existing callers keep working. An
  identifier the mapper cannot resolve raises `ExceptionHandler` with
  `404` and the mapper's own explanation.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from src.clients.mapping.api.resolve import resolve as resolve_op
from src.clients.mapping.client import AuthenticatedClient
from src.clients.mapping.models.problem import Problem
from src.clients.mapping.models.resolve_request import ResolveRequest
from src.clients.mapping.models.resolve_response import ResolveResponse
from src.shared.config import system_config
from src.shared.exceptions import ExceptionHandler
from src.shared.utils.urls import is_https_url

_NOT_RESOLVED = "The mapping service could not resolve this identifier."


@dataclass(frozen=True)
class ResolvedRef:
    """Outcome of resolving an identifier.

    `repo_url` is the https URL `git clone` should target and
    `identifier` echoes what was asked for.
    """

    repo_url: str
    identifier: str


class MappingServiceClient:
    """Call the mapping microservice via the generated HTTP client."""

    async def resolve(self, identifier: str) -> ResolvedRef:
        """Resolve `identifier` via the mapping service, or identity-pass it.

        Raises `ExceptionHandler` if the mapping service is enabled but the
        call fails (timeout, unreachable, bad status) or returns an
        unexpected response — callers should treat that as a fatal request
        error, not silently fall back to identity (which would mask
        misconfiguration). 504 for timeouts, 502 otherwise.
        """
        cfg = system_config.services.mapping
        if not cfg.enabled or not cfg.endpoint:
            # Identity passthrough: the identifier is taken as the repo URL.
            return ResolvedRef(repo_url=identifier, identifier=identifier)

        body = ResolveRequest(identifier=identifier)
        client = AuthenticatedClient(
            base_url=cfg.endpoint,
            token=cfg.token,
            timeout=httpx.Timeout(10.0),
        )
        try:
            async with client as c:
                detailed = await resolve_op.asyncio_detailed(client=c, body=body)
        except httpx.TimeoutException as e:
            raise ExceptionHandler(f"mapping service timed out: {e}", 504) from e
        except httpx.RequestError as e:
            raise ExceptionHandler(f"mapping service unreachable: {e}", 502) from e
        except (ValueError, TypeError, KeyError) as e:
            # Deserialising the body: a non-JSON payload raises
            # JSONDecodeError (a ValueError), a missing required field
            # raises KeyError. Both mean the response is off-contract.
            raise ExceptionHandler(
                f"mapping service returned an unparseable response: {e!r}", 502
            ) from e
        response = detailed.parsed
        if detailed.status_code == 404:
            # The contract's clean "not in our catalogue": the caller's
            # input is wrong, not the sidecar, so say so with its reason.
            reason = response.detail if isinstance(response, Problem) else None
            raise ExceptionHandler(
                reason if isinstance(reason, str) and reason else _NOT_RESOLVED, 404
            )
        if not isinstance(response, ResolveResponse):
            raise ExceptionHandler(
                f"mapping service returned an unexpected response: {response!r}", 502
            )
        if not is_https_url(response.repo_url):
            raise ExceptionHandler(
                "mapping service returned a repo_url that is not an https:// URL", 502
            )
        return ResolvedRef(repo_url=response.repo_url, identifier=response.identifier)
