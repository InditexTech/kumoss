# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import hashlib
import json
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

import deepdiff

from src.shared.exceptions import ExceptionHandler


class TerraformUtils:
    @staticmethod
    def project_id(repo_uri: str, scope_id: str, iac_path: str) -> str:
        """Identify the Terraform project a session operates on.

        Digest over the triple that decides which state a run belongs
        to: the repository, the cloud scope it deploys into, and the
        root module within the repository. Independent of where the
        repository was cloned, so every call and every session on the
        same project resolves to the same state — which the clone
        directory, recreated per call, cannot express.

        The repository URI is normalized first: it reaches here in
        whatever form the caller used, and credentials embedded for
        push, a ``.git`` suffix or a different case must not split one
        project into several.
        """
        seed = "\n".join(
            (
                TerraformUtils.__normalize_repo_uri(repo_uri),
                scope_id.strip().lower(),
                TerraformUtils.__normalize_iac_path(iac_path or ""),
            )
        )
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()

    @staticmethod
    def __normalize_repo_uri(repo_uri: str) -> str:
        uri = repo_uri.strip()
        if "://" not in uri and "@" in uri:
            uri = "ssh://" + uri.replace(":", "/", 1)
        parsed = urlparse(uri)
        host = (parsed.hostname or "").lower()
        path = parsed.path.strip("/").removesuffix(".git").strip("/").lower()
        return f"{host}/{path}"

    @staticmethod
    def __normalize_iac_path(iac_path: str) -> str:
        path = iac_path.strip().strip("/")
        return PurePosixPath(path).as_posix() if path else ""

    @staticmethod
    def plan_to_drift(
        plan_json: dict[str, Any], reversed: bool = False
    ) -> list[dict[str, Any]]:
        if float(plan_json["format_version"]) >= 2.0:
            raise ExceptionHandler(
                message="Terraform plan json output major format change.",
                error_code=500,
            )
        resources = TerraformUtils.__get_resource_changes(plan_json)
        if reversed:
            resources = TerraformUtils.__reverse_output(resources)
        return resources

    @staticmethod
    def __get_resource_changes(plan: dict[str, Any]) -> list[dict[str, Any]]:
        changed_resources: list[dict[str, Any]] = []
        if not plan.get("resource_changes"):
            return changed_resources
        for resource in plan["resource_changes"]:
            actions_resource: list[Any] = resource["change"]["actions"]
            if actions_resource[0] in ["update", "create", "delete"]:
                changed_resources.append(resource)
        filtered_changes: list[dict[str, Any]] = []
        for resource in changed_resources:
            actions: list[str] = resource["change"]["actions"]
            if actions == ["update"] or actions == ["delete", "create"]:
                before: dict[str, Any] = resource["change"]["before"]
                after: dict[str, Any] = resource["change"]["after"]
                diff = deepdiff.DeepDiff(before, after, verbose_level=2)
                if diff:
                    filtered_changes.append(
                        {
                            "address": resource["address"],
                            "action": "update resource",
                            "changes": json.loads(diff.to_json()),
                        }
                    )
            elif actions == ["create"]:
                filtered_changes.append(
                    {
                        "address": resource["address"],
                        "action": "delete resource",
                    }
                )
            elif actions == ["delete"]:
                filtered_changes.append(
                    {
                        "address": resource["address"],
                        "action": "create resource",
                        "changes": resource["change"]["before"],
                    }
                )
        return filtered_changes

    @staticmethod
    def __reverse_output(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for resource in changes:
            if resource["action"] == "update resource":
                resource["changes"] = {
                    TerraformUtils.__swap_word(
                        category, ("added", "removed")
                    ): TerraformUtils.__reverse_items(items)
                    if category in ("values_changed", "type_changes")
                    else items
                    for category, items in resource["changes"].items()
                }
        return changes

    @staticmethod
    def __reverse_items(items: dict[str, dict[str, Any]]) -> dict[str, Any]:
        return {
            path: {
                TerraformUtils.__swap_word(field, ("old", "new")): value
                for field, value in change.items()
            }
            for path, change in items.items()
        }

    @staticmethod
    def __swap_word(key: str, pair: tuple[str, str]) -> str:
        a, b = pair
        parts = key.split("_")
        return "_".join(b if p == a else a if p == b else p for p in parts)
