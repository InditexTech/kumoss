# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import re

from src.domains.dto import (
    TerraformPlanParseDTO,
    TerraformPlanParseObject,
    TerraformPlanResource,
)
from src.infrastructure.exceptions import TerraformResourceNotFoundException


class TerraformPlanParser:
    def __init__(self, tf_plan: str) -> None:
        self.__tf_plan: str = tf_plan

    def filter_duplicates(self) -> TerraformPlanParseDTO:
        # construct list of TerraformPlanResource objs
        resources: list[TerraformPlanResource] = self.__parse_resources()

        # final resouces lists
        add_res: list[TerraformPlanResource] = []
        rm_res: list[TerraformPlanResource] = []

        # create a hashmap for id -> count
        hash_resources: dict[str, int] = {}  # id -> count
        for r in resources:
            if not r.id:
                add_res.append(r)
            elif r.id in hash_resources:
                hash_resources[r.id] += 1
            else:
                hash_resources[r.id] = 1

        for r_id, c in hash_resources.items():
            if c == 1:
                resource: TerraformPlanResource = self.__find_resource_id(
                    resources=resources,
                    resource_id=r_id,
                )
                if resource.content.count("+ ") >= 2:
                    add_res.append(resource)
                else:
                    rm_res.append(resource)

        return TerraformPlanParseDTO(
            added=TerraformPlanParseObject(add_res, len(add_res)),
            removed=TerraformPlanParseObject(rm_res, len(rm_res)),
        )

    def __find_resource_id(
        self, resources: list[TerraformPlanResource], resource_id: str
    ) -> TerraformPlanResource:
        for r in resources:
            if resource_id == r.id:
                return r
        raise TerraformResourceNotFoundException(
            message=f"Terraform resource with ID '{resource_id}' is not found.",
            error_code=500,
        )

    def __parse_resources(self) -> list[TerraformPlanResource]:
        # Pattern to match the entire resource block
        pattern = r"^\s*[+\-]\s+([a-z_]+)\s+\{(.*?)\n\s*\}"

        # Using DOTALL flag to match across multiple lines
        resource_pattern = re.compile(pattern, re.DOTALL | re.MULTILINE)

        # To extract the ID from within the block
        id_pattern = r'^\s*[-+]?\s*id\s*=\s*"([^"]+)"'

        resources: list[TerraformPlanResource] = []

        for match in resource_pattern.finditer(self.__tf_plan):
            resource_type = match.group(1)
            resource_body = match.group(2)
            full_definition = match.group(0)

            # Extract the ID from the resource body
            id_match = re.search(id_pattern, resource_body, re.MULTILINE)
            resource_id = id_match.group(1) if id_match else None

            resources.append(
                TerraformPlanResource(
                    type=resource_type,
                    id=resource_id,
                    content=full_definition,
                )
            )

        return resources
