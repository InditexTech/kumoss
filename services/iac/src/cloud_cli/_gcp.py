# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""GCP: service-account activation via ``gcloud`` and asset/IAM listing."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from ..engine import CommandResult
from ..models import LoginError
from ._base import CloudProvider, _failure, _ids_result, _run


class GcpProvider(CloudProvider):
    name = "gcp"
    display_name = "GCP"
    cli_binary = "gcloud"

    def credential_env(self) -> dict[str, str]:
        return {"GOOGLE_CREDENTIALS": self._config.google_credentials}

    async def login(self) -> None:
        """Activate the service account from the inline key JSON.

        ``gcloud`` only accepts a key *file*, so the JSON is written to a
        0600 temp file for the duration of the command and removed
        afterwards; gcloud copies the key into its own credential store
        during activation.
        """
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
        tmp_key_path = Path(tmp.name)
        try:
            tmp.write(self._config.google_credentials)
            tmp.close()
            result = await _run(
                [
                    "gcloud",
                    "auth",
                    "activate-service-account",
                    f"--key-file={tmp_key_path}",
                ]
            )
            if not result.ok:
                raise LoginError({self.display_name: result.stderr.strip()})
        finally:
            tmp_key_path.unlink(missing_ok=True)

    async def scope_env(self, scope_id: str) -> dict[str, str]:
        return {"GOOGLE_PROJECT": scope_id}

    async def list_resource_ids(self, scope_id: str) -> CommandResult:
        """List GCP resources and IAM roles; returned IDs mix both types."""
        resources_result, iam_result = await asyncio.gather(
            _run(
                [
                    "gcloud",
                    "asset",
                    "search-all-resources",
                    f"--scope=projects/{scope_id}",
                    "--format=json",
                ]
            ),
            _run(
                [
                    "gcloud",
                    "asset",
                    "search-all-iam-policies",
                    f"--scope=projects/{scope_id}",
                    "--format=json",
                ]
            ),
        )

        errors = []
        if not resources_result.ok:
            errors.append(f"Resources: {resources_result.stderr}")
        if not iam_result.ok:
            errors.append(f"IAM: {iam_result.stderr}")
        if errors:
            return _failure("\n".join(errors))

        try:
            raw_resources = json.loads(resources_result.stdout)
            raw_iam = json.loads(iam_result.stdout)
        except json.JSONDecodeError as exc:
            return _failure(f"gcloud returned unparsable JSON: {exc}")

        # gcloud --format=json emits an array, but tolerate the REST-style
        # {"results": [...]} wrapper too.
        assets = (
            raw_resources.get("results", raw_resources)
            if isinstance(raw_resources, dict)
            else raw_resources
        )
        iam_policies = (
            raw_iam.get("results", raw_iam) if isinstance(raw_iam, dict) else raw_iam
        )
        try:
            ids = [a["name"] for a in assets if "name" in a]
            for policy_entry in iam_policies:
                for binding in policy_entry.get("policy", {}).get("bindings", []):
                    role = binding.get("role", "")
                    if role and role not in ids:
                        ids.append(role)
        except (AttributeError, TypeError) as exc:
            # Valid JSON but not the asset / policy shape gcloud documents;
            # report it like any other listing failure instead of a job 500.
            return _failure(f"gcloud returned an unexpected JSON shape: {exc}")

        return _ids_result(ids)
