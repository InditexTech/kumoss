# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from sqlalchemy import inspect
from src.infrastructure.database.models import UserSession


class TestUserSessionSchema(unittest.TestCase):
    """The schema must match the spec's session row shape."""

    def setUp(self):
        self.cols = {c.name: c for c in inspect(UserSession).columns}

    def test_has_new_columns(self):
        for name in (
            "session_id",
            "user_id",
            "repo_uri",
            "cloud_provider",
            "environment",
            "branch_name",
            "status",
            "in_flight",
            "history",
            "last_payload",
            "created_at",
            "updated_at",
            "operation_type",
            "failure_reason",
            "pull_request_url",
            "apply_allowed",
            "iac_path",
        ):
            self.assertIn(name, self.cols, f"missing column: {name}")

    def test_dropped_legacy_columns(self):
        for name in (
            "repository_id",
            "initial_query",
            "current_status",
            "final_status",
            "is_active",
            "completed_at",
            "duration_seconds",
            "cloud_portal_url",
        ):
            self.assertNotIn(name, self.cols, f"legacy column still present: {name}")

    def test_observability_column_defaults(self):
        """Four restored observability columns must have the correct defaults."""
        # operation_type defaults to "generate" (string scalar)
        self.assertEqual(self.cols["operation_type"].default.arg, "generate")
        # apply_allowed defaults to True (bool scalar)
        self.assertTrue(self.cols["apply_allowed"].default.arg)
        # failure_reason and pull_request_url are nullable with no default
        self.assertTrue(self.cols["failure_reason"].nullable)
        self.assertTrue(self.cols["pull_request_url"].nullable)

    def test_in_flight_default_false(self):
        self.assertFalse(self.cols["in_flight"].default.arg)

    def test_status_not_nullable(self):
        self.assertFalse(self.cols["status"].nullable)

    def test_status_has_check_constraint(self):
        from sqlalchemy.schema import CheckConstraint

        constraints = [
            c
            for c in UserSession.__table__.constraints
            if isinstance(c, CheckConstraint)
        ]
        self.assertTrue(
            any("status" in str(c.sqltext) for c in constraints),
            "expected a CheckConstraint on `status`",
        )

    def test_history_default_is_list_callable(self):
        # SQLAlchemy gotcha: default=list (callable) gives each row its own
        # empty list; default=[] would share one mutable list across rows.
        # SQLAlchemy 2.x wraps the callable, so we verify is_callable=True
        # and that the underlying function is named "list" (i.e. the built-in).
        default = self.cols["history"].default
        self.assertTrue(
            default.is_callable, "history default must be a callable, not a scalar"
        )
        self.assertEqual(default.arg.__name__, "list")
