# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Azure: service-principal login via ``az`` and Resource Graph listing."""

from __future__ import annotations

import json

from ..engine import CommandResult
from ..models import LoginError
from ._base import CloudProvider, _failure, _ids_result, _run

_GRAPH_PAGE_SIZE = 1000
_GRAPH_MAX_PAGES = 100


class AzureProvider(CloudProvider):
    name = "azure"
    display_name = "Azure"
    cli_binary = "az"

    def credential_env(self) -> dict[str, str]:
        return {
            "ARM_CLIENT_ID": self._config.azure_client_id,
            "ARM_CLIENT_SECRET": self._config.azure_client_secret,
            "ARM_TENANT_ID": self._config.azure_tenant_id,
        }

    async def login(self) -> None:
        # The client secret travels on argv, so it is readable from
        # /proc/<pid>/cmdline by any process in the same PID namespace for
        # the lifetime of the (short) `az login` call. Acceptable inside the
        # single-purpose service container; a certificate or federated
        # token (`--federated-token`) would avoid it if that ever changes.
        result = await _run(
            [
                "az",
                "login",
                "--service-principal",
                "-u",
                self._config.azure_client_id,
                "-p",
                self._config.azure_client_secret,
                "--tenant",
                self._config.azure_tenant_id,
                "--allow-no-subscriptions",
            ]
        )
        if not result.ok:
            raise LoginError({self.display_name: result.stderr.strip()})

    async def scope_env(self, scope_id: str) -> dict[str, str]:
        return {"ARM_SUBSCRIPTION_ID": scope_id}

    async def list_resource_ids(self, scope_id: str) -> CommandResult:
        # scope_id is caller-controlled; escape it so it cannot terminate
        # the KQL string literal and alter the query.
        quoted = scope_id.replace("\\", "\\\\").replace("'", "\\'")
        query = (
            f"resources | where id contains '{quoted}' | project id"
            f" | union (resourcecontainers | where id contains '{quoted}' | project id)"
        )
        # Resource Graph pages at 1000 rows; follow skip_token so larger
        # scopes are not silently truncated.
        rows: list[dict] = []
        skip_token: str | None = None
        for _ in range(_GRAPH_MAX_PAGES):
            command = [
                "az",
                "graph",
                "query",
                "-q",
                query,
                "--first",
                str(_GRAPH_PAGE_SIZE),
                "--output",
                "json",
            ]
            if skip_token:
                command.extend(["--skip-token", skip_token])
            result = await _run(command)
            if not result.ok:
                return _failure(result.stderr, result.exit_code)
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                return _failure(f"az graph query returned unparsable JSON: {exc}")
            rows.extend(payload.get("data", []))
            skip_token = payload.get("skip_token")
            if not skip_token:
                break

        if skip_token:
            return _failure(
                f"az graph query exceeded max pages ({_GRAPH_MAX_PAGES}); "
                "refusing to truncate results"
            )

        return _ids_result([row["id"] for row in rows if "id" in row])
