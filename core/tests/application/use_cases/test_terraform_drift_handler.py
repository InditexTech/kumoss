# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""What the drift handler puts in the report content.

The report generator reads this content as the round's story, so
everything a user must know about the outcome has to be in it: the drift
that could not be reconciled, and the drift that was left alone on
purpose because an exception rule covers it.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock

from src.application.use_cases.terraform_drift_handler import TerraformDriftHandler
from src.domains.dto import TerraformDriftDTO


def _drift_dto(
    in_sync: bool,
    excluded: list[str] | None = None,
) -> TerraformDriftDTO:
    return TerraformDriftDTO(
        in_sync=in_sync,
        drift="" if in_sync else "[drift]",
        feedback="",
        stdout="plan output",
        plan=None,
        excluded=excluded or [],
    )


class TestDriftHandlerReportContent(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session_svc = AsyncMock()
        self.template_svc = AsyncMock()
        self.filter_svc = AsyncMock()
        self.filter_svc.filter.return_value = (True, "")
        self.report_svc = AsyncMock()
        self.target_svc = AsyncMock()
        self.drift_svc = AsyncMock()
        self.ctx = MagicMock()
        self.ctx.history.serialize.return_value = [{"user": "check drift"}]

    def _handler(self) -> TerraformDriftHandler:
        return TerraformDriftHandler(
            session_ctx=self.ctx,
            session_service=self.session_svc,
            template_service=self.template_svc,
            requests_filter_service=self.filter_svc,
            report_service=self.report_svc,
            target_service=self.target_svc,
            drift_service=self.drift_svc,
        )

    async def _content(self, drift: TerraformDriftDTO) -> str:
        self.drift_svc.detect_and_resolve_drift.return_value = drift
        task = await self._handler().handle("check drift", is_partial=False)
        await task()
        return self.report_svc.generate_report.await_args.kwargs["content"]

    async def test_exclusions_reach_the_report_content(self):
        content = await self._content(
            _drift_dto(True, excluded=["rule 1 protects module.kvt_001"])
        )

        self.assertIn("rule 1 protects module.kvt_001", content)

    async def test_every_iteration_note_reaches_the_report_content(self):
        content = await self._content(
            _drift_dto(True, excluded=["first note", "second note"])
        )

        self.assertIn("first note", content)
        self.assertIn("second note", content)

    async def test_exclusions_sit_beside_the_unreconciled_note(self):
        content = await self._content(_drift_dto(False, excluded=["rule 1"]))

        self.assertIn("this drift couldn't be reconcile", content)
        self.assertIn("[drift]", content)
        self.assertIn("rule 1", content)

    async def test_nothing_is_appended_when_nothing_was_excluded(self):
        content = await self._content(_drift_dto(True))

        # A round with no exclusions must not claim there were any.
        self.assertNotIn("exception rules", content)
        self.assertEqual(content, '[{"user": "check drift"}]')


if __name__ == "__main__":
    unittest.main()
