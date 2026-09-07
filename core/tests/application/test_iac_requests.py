# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from uuid import UUID

from pydantic import ValidationError

from src.application.iac_requests import (
    GenerateRequest,
    DriftRequest,
    ApplyRequest,
)

_SID = UUID("11111111-1111-1111-1111-111111111111")


class TestGenerateRequest(unittest.TestCase):
    def test_first_call_shape(self):
        req = GenerateRequest(
            repo_uri="https://example.com/foo.git",
            terraform_providers="azure",
            scope_id="sub-123",
            q="create storage account",
        )
        self.assertEqual(req.repo_uri, "https://example.com/foo.git")
        self.assertIsNone(req.session_id)

    def test_iteration_call_shape(self):
        req = GenerateRequest(session_id=str(_SID), q="now add a key vault")
        self.assertEqual(req.session_id, _SID)
        self.assertIsNone(req.repo_uri)

    def test_rejects_both_uri_and_session_id(self):
        with self.assertRaises(ValidationError):
            GenerateRequest(
                repo_uri="https://example.com/foo.git",
                session_id=str(_SID),
                terraform_providers="azure",
                q="x",
            )

    def test_rejects_neither(self):
        with self.assertRaises(ValidationError):
            GenerateRequest(q="x")

    def test_first_call_requires_terraform_providers(self):
        with self.assertRaises(ValidationError):
            GenerateRequest(repo_uri="https://example.com/foo.git", q="x")


class TestDriftRequest(unittest.TestCase):
    def test_drift_first_call(self):
        req = DriftRequest(
            repo_uri="https://example.com/foo.git",
            terraform_providers="azure",
            q="check drift",
            is_partial=True,
        )
        self.assertTrue(req.is_partial)
        self.assertEqual(req.q, "check drift")

    def test_drift_defaults_to_full(self):
        req = DriftRequest(
            repo_uri="https://example.com/foo.git",
            terraform_providers="azure",
            q="detect all drift",
        )
        self.assertFalse(req.is_partial)

    def test_partial_with_blank_query_is_rejected(self):
        with self.assertRaises(ValidationError):
            DriftRequest(
                repo_uri="https://example.com/foo.git",
                terraform_providers="azure",
                is_partial=True,
                q=" ",
            )


class TestApplyRequest(unittest.TestCase):
    def test_apply_takes_only_a_session_id(self):
        req = ApplyRequest(session_id=str(_SID))
        self.assertEqual(req.session_id, _SID)

    def test_apply_requires_a_session_id(self):
        with self.assertRaises(ValidationError):
            ApplyRequest()
