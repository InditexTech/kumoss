# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""The target generator sentinel enforces `services.iac.max_plan_targets`.

A list the iac sidecar would reject must come back to the model as the
tool's error, with no result, so the chain keeps going and the model
consolidates its own list instead of the session failing at plan time.
"""

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from src.domains.dto import ToolCallDTO, ToolResultDTO
from src.infrastructure.tools import tool_registry_static
from src.infrastructure.tools.tool_registry_static import ToolRegistryStatic


class TestTargetGeneratorLimit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry = ToolRegistryStatic(summarizer=MagicMock())
        patcher = patch.object(
            tool_registry_static,
            "system_config",
            SimpleNamespace(services=SimpleNamespace(iac=SimpleNamespace(max_plan_targets=3))),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _generate(self, targets: Any) -> ToolResultDTO:
        return await self.registry.execute_tool(
            ToolCallDTO(
                id="call_1",
                name="generate_terraform_targets",
                parameters={"targets": targets, "explanation": "why"},
            )
        )

    async def test_targets_within_the_limit_are_returned(self):
        result = await self._generate(["module.a", "aws_s3_bucket.b", "module.c"])

        self.assertTrue(result.success, result.error_message)
        self.assertEqual(
            result.result,
            {"targets": ["module.a", "aws_s3_bucket.b", "module.c"], "explanation": "why"},
        )

    async def test_targets_over_the_limit_go_back_as_an_error(self):
        result = await self._generate([f"module.m{i}" for i in range(4)])

        self.assertFalse(result.success)
        self.assertIsNone(result.result)
        self.assertIn("4 targets exceed the limit of 3", result.error_message)
        self.assertIn("module.<name>", result.error_message)

    async def test_a_target_longer_than_the_contract_allows_is_an_error(self):
        result = await self._generate(["module." + "x" * 1024])

        self.assertFalse(result.success)
        self.assertIn("above the limit of 1024", result.error_message)

    async def test_an_empty_target_is_an_error(self):
        result = await self._generate(["module.a", ""])

        self.assertFalse(result.success)
        self.assertIn("non-empty string", result.error_message)


if __name__ == "__main__":
    unittest.main()
