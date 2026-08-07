# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import json
from typing import Any

import deepdiff

from src.shared.exceptions import ExceptionHandler


class TerraformUtils:
    @staticmethod
    def plan_to_drift(
        plan_json: dict[str, Any], reversed: bool = False
    ) -> list[dict[str, Any]]:
        if float(plan_json["format_version"]) >= 2.0:
            raise ExceptionHandler(
                message="Terraform plan json output major format change."
                + "Please contact with the devops team",
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
                changed_resource = (
                    json.dumps(resource["changes"])
                    .replace("old", "%old%")
                    .replace("new", "old")
                    .replace("%old%", "new")
                    .replace("added", "%added%")
                    .replace("removed", "added")
                    .replace("%added%", "removed")
                )
                resource["changes"] = json.loads(changed_resource)
        return changes
