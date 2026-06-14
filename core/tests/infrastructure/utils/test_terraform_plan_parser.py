# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic, reportAssignmentType=false, reportAttributeAccessIssue=false
import unittest
from pathlib import Path

from src.domains.dto import (
    TerraformPlanParseDTO,
)
from src.infrastructure.utils.terraform_plan_parser import TerraformPlanParser


class TestTerraformParser(unittest.IsolatedAsyncioTestCase):
    def test_parse_dto(self):
        with open(Path(".") / "infrastructure/utils/add_plan.txt", "r") as f:
            plan = f.read()
        parser = TerraformPlanParser(plan)
        output = parser.parse()
        self.assertIsInstance(output, TerraformPlanParseDTO)

    def test_parse_add(self):
        with open(Path(".") / "infrastructure/utils/add_plan.txt", "r") as f:
            plan = f.read()
        parser = TerraformPlanParser(plan)
        output = parser.parse()
        self.assertEqual(output.added.count, 8)
        self.assertEqual(output.added.resources[0].type, "backend_address_pool")
        self.assertEqual(output.removed.count, 0)

    def test_parse_delete(self):
        with open(Path(".") / "infrastructure/utils/delete_plan.txt", "r") as f:
            plan = f.read()
        parser = TerraformPlanParser(plan)
        output = parser.parse()
        self.assertEqual(output.removed.count, 8)
        self.assertEqual(output.removed.resources[0].type, "backend_address_pool")
        self.assertEqual(output.added.count, 0)

    def test_parse_redirect(self):
        with open(Path(".") / "infrastructure/utils/redirect_plan.txt", "r") as f:
            plan = f.read()
        parser = TerraformPlanParser(plan)
        output = parser.parse()
        self.assertEqual(output.removed.count, 2)
        self.assertEqual(output.added.count, 3)

    def test_parse_replace(self):
        with open(Path(".") / "infrastructure/utils/replace_plan.txt", "r") as f:
            plan = f.read()
        parser = TerraformPlanParser(plan)
        output = parser.parse()
        self.assertEqual(output.removed.count, 3)
        self.assertEqual(output.added.count, 3)


if __name__ == "__main__":
    unittest.main()
