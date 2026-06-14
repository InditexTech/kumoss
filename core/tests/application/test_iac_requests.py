# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest

from pydantic import ValidationError

from src.application.iac_requests import (
    GenerateRequest,
    DriftRequest,
    ApplyRequest,
)


class TestGenerateRequest(unittest.TestCase):
    def test_first_call_shape(self):
        req = GenerateRequest(
            repo_uri="https://example.com/foo.git",
            cloud="azure",
            environment="dev",
            user_id="u@e.com",
            q="create storage account",
        )
        self.assertEqual(req.repo_uri, "https://example.com/foo.git")
        self.assertIsNone(req.session_id)

    def test_iteration_call_shape(self):
        req = GenerateRequest(
            session_id="11111111-1111-1111-1111-111111111111",
            user_id="u@e.com",
            q="now add a key vault",
        )
        self.assertEqual(req.session_id, "11111111-1111-1111-1111-111111111111")
        self.assertIsNone(req.repo_uri)

    def test_rejects_both_uri_and_session_id(self):
        with self.assertRaises(ValidationError):
            GenerateRequest(
                repo_uri="https://example.com/foo.git",
                session_id="11111111-1111-1111-1111-111111111111",
                cloud="azure",
                environment="dev",
                user_id="u",
                q="x",
            )

    def test_rejects_neither(self):
        with self.assertRaises(ValidationError):
            GenerateRequest(user_id="u", q="x")

    def test_first_call_requires_cloud_and_environment(self):
        with self.assertRaises(ValidationError):
            GenerateRequest(
                repo_uri="https://example.com/foo.git",
                user_id="u",
                q="x",
            )


class TestDriftRequest(unittest.TestCase):
    def test_drift_specific_field(self):
        req = DriftRequest(
            repo_uri="https://example.com/foo.git",
            cloud="azure",
            environment="dev",
            user_id="u",
            q="check drift",
            is_partial=True,
        )
        self.assertTrue(req.is_partial)


class TestApplyRequest(unittest.TestCase):
    def test_apply_specific_field(self):
        req = ApplyRequest(
            session_id="11111111-1111-1111-1111-111111111111",
            user_id="u",
            q="apply",
            terraform_targets=["module.foo"],
        )
        self.assertEqual(req.terraform_targets, ["module.foo"])
