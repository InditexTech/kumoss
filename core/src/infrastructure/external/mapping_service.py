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

- `MappingServiceClient.resolve(identifier, terraform_provider)` →
  `ResolvedRef(repo_url, identifier, terraform_provider, scope_id)`.
  Returns identity passthrough when mapping is disabled so existing
  callers keep working.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from src.clients.mapping.api.resolve import resolve as resolve_op
from src.clients.mapping.client import AuthenticatedClient
from src.clients.mapping.models.resolve_request import ResolveRequest
from src.clients.mapping.models.resolve_response import ResolveResponse
from src.clients.mapping.models.terraform_provider import (
    TerraformProvider as MappingTerraformProvider,
)
from src.clients.mapping.types import UNSET, Unset
from src.shared.config import system_config
from src.shared.constants import TerraformProvider
from src.shared.exceptions import ExceptionHandler


@dataclass(frozen=True)
class ResolvedRef:
    """Outcome of resolving an identifier.

    `repo_url` is what `git clone` should target and `identifier` echoes
    what was asked for. `terraform_provider` and `scope_id` are the
    mapper's best effort: `None` means "unknown, ask the user", never
    "there is none". Callers skip the prompt for whatever is filled in,
    so an unknown value must stay `None`.
    """

    repo_url: str
    identifier: str
    terraform_provider: TerraformProvider | None = None
    scope_id: str | None = None


def _unwrap(value: str | None | Unset) -> str | None:
    return None if isinstance(value, Unset) else value


def _core_provider(
    value: MappingTerraformProvider | str | None | Unset,
) -> TerraformProvider | None:
    """Convert the client's enum to core's, rejecting anything else.

    The contract's `anyOf: [$ref, null]` makes the generated parser
    swallow the `ValueError` from an out-of-enum value and hand back the
    raw string, so `"azurerm"` arrives here as a `str`. Passing it on
    would blow up later as an unhandled 500.
    """
    if value is None or isinstance(value, Unset):
        return None
    if isinstance(value, MappingTerraformProvider):
        return TerraformProvider(value.value)
    raise ExceptionHandler(
        f"mapping service returned an unknown terraform_provider: {value!r}", 502
    )


class MappingServiceClient:
    """Call the mapping microservice via the generated HTTP client."""

    async def resolve(
        self,
        identifier: str,
        *,
        terraform_provider: TerraformProvider | None = None,
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
            # Byte-identical to what the reference service answers, so
            # toggling `mapping.enabled` changes nothing for a user who
            # pastes a repo URL.
            return ResolvedRef(
                repo_url=identifier,
                identifier=identifier,
                terraform_provider=terraform_provider,
                scope_id=None,
            )

        body = ResolveRequest(
            identifier=identifier,
            terraform_provider=(
                MappingTerraformProvider(terraform_provider.value)
                if terraform_provider is not None
                else UNSET
            ),
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
        except (ValueError, TypeError, KeyError) as e:
            # Deserialising the body: a non-JSON payload raises
            # JSONDecodeError (a ValueError), a missing required field
            # raises KeyError. Both mean the response is off-contract.
            raise ExceptionHandler(
                f"mapping service returned an unparseable response: {e!r}", 502
            ) from e
        if not isinstance(response, ResolveResponse):
            raise ExceptionHandler(
                f"mapping service returned an unexpected response: {response!r}", 502
            )
        return ResolvedRef(
            repo_url=response.repo_url,
            identifier=response.identifier,
            terraform_provider=_core_provider(response.terraform_provider),
            scope_id=_unwrap(response.scope_id),
        )
