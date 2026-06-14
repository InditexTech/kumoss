# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# pyright: basic, reportAssignmentType=false, reportAttributeAccessIssue=false
import unittest
import json
from pathlib import Path
from pprint import pprint

from src.infrastructure.validators._utils import TerraformValidatorUtils


class TestTerraformDrift(unittest.IsolatedAsyncioTestCase):
    main_service: TerraformValidatorUtils = TerraformValidatorUtils()

    async def test_plan_to_drift_works(self):
        with open(Path(".") / "cors_aca_full_drift_v2.json", "r") as f:
            plan = f.read()
        output = self.main_service.plan_to_drift(json.loads(plan))
        pprint(output)
        print(len(output))
        self.assertIsInstance(output, list)

    async def test_plan_to_drift_revesed_works(self):
        with open(Path(".") / "cors_aca_full_drift_v2.json", "r") as f:
            plan = f.read()
        output = self.main_service.plan_to_drift(json.loads(plan), True)
        self.assertIsInstance(output, list)


if __name__ == "__main__":
    unittest.main()
