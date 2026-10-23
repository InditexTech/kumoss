# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""`plan_targets_violation` mirrors the iac contract's `targets` caps."""

import unittest

from src.shared.constants import PLAN_TARGET_MAX_LENGTH, PLAN_TARGETS_MAX_BYTES
from src.shared.utils.plan_targets import plan_targets_violation


class TestPlanTargetsViolation(unittest.TestCase):
    def test_no_targets_plan_everything(self):
        self.assertIsNone(plan_targets_violation([], limit=1))

    def test_a_list_at_the_limit_is_accepted(self):
        self.assertIsNone(plan_targets_violation(["module.a", "module.b"], limit=2))

    def test_a_list_over_the_limit_is_rejected(self):
        violation = plan_targets_violation(["module.a", "module.b"], limit=1)
        self.assertIsNotNone(violation)
        self.assertIn("2 targets exceed the limit of 1", violation)

    def test_a_target_at_the_length_cap_is_accepted(self):
        self.assertIsNone(
            plan_targets_violation(["t" * PLAN_TARGET_MAX_LENGTH], limit=1)
        )

    def test_a_target_over_the_length_cap_is_rejected(self):
        violation = plan_targets_violation(
            ["t" * (PLAN_TARGET_MAX_LENGTH + 1)], limit=1
        )
        self.assertIsNotNone(violation)
        self.assertIn(f"limit of {PLAN_TARGET_MAX_LENGTH}", violation)

    def test_the_byte_cap_counts_utf8_bytes(self):
        # 2048 targets of 512 two-byte characters are exactly 1 MiB of
        # characters, which a character count would accept, but 2 MiB of
        # bytes.
        targets = ["é" * 512] * (PLAN_TARGETS_MAX_BYTES // 512)
        violation = plan_targets_violation(targets, limit=len(targets))
        self.assertIsNotNone(violation)
        self.assertIn(f"limit of {PLAN_TARGETS_MAX_BYTES}", violation)

    def test_the_advice_consolidates_and_never_drops_targets(self):
        # Every target is a branch change or a dependant of one: a list
        # cut down to fit would plan an incomplete change.
        over_count = plan_targets_violation(["module.a", "module.b"], limit=1)
        over_bytes = plan_targets_violation(
            ["t" * 512] * (PLAN_TARGETS_MAX_BYTES // 512 + 1), limit=4096
        )
        for violation in (over_count, over_bytes):
            assert violation is not None
            self.assertIn("module.<name>", violation)
            self.assertIn("Never drop a target", violation)
            self.assertNotIn("keep only", violation)
        assert over_count is not None and over_bytes is not None
        self.assertIn("services.iac.max_plan_targets", over_count)
        self.assertNotIn("services.iac.max_plan_targets", over_bytes)

    def test_non_string_targets_are_rejected(self):
        self.assertIsNotNone(plan_targets_violation(["module.a", 3], limit=2))


if __name__ == "__main__":
    unittest.main()
