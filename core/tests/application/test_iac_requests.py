# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from src.application.iac_requests import (
    GenerateRequest,
    DriftRequest,
    ApplyRequest,
    RepoUri,
)

_SID = UUID("11111111-1111-1111-1111-111111111111")


class TestRepoUri(unittest.TestCase):
    def setUp(self):
        self.adapter = TypeAdapter(RepoUri)

    def test_bare_https_uri_passes_through(self):
        uri = "https://github.com/foo/bar.git"
        self.assertEqual(self.adapter.validate_python(uri), uri)

    def test_mixed_case_https_scheme_passes_through(self):
        uri = "Https://github.com/foo/bar.git"
        self.assertEqual(self.adapter.validate_python(uri), uri)

    def test_rejects_every_non_https_transport(self):
        for uri in (
            "git@github.com:foo/bar.git",
            "ssh://git@github.com/foo/bar.git",
            "git+ssh://git@github.com/foo/bar.git",
            "git://github.com/foo/bar.git",
            "http://github.com/foo/bar.git",
            "file:///srv/git/bar.git",
            "/srv/git/bar.git",
            "github.com/foo/bar.git",
        ):
            with self.subTest(uri=uri):
                with self.assertRaises(ValidationError) as ctx:
                    _ = self.adapter.validate_python(uri)
                self.assertIn("https://", str(ctx.exception))

    def test_rejects_https_without_a_host(self):
        for uri in ("https://", "https:///foo/bar.git"):
            with self.subTest(uri=uri):
                with self.assertRaises(ValidationError):
                    _ = self.adapter.validate_python(uri)

    def test_https_uri_with_a_username_passes_through_verbatim(self):
        uri = "https://InditexData@dev.azure.com/InditexData/DevOpsv2/_git/devops.project.greenai"
        self.assertEqual(self.adapter.validate_python(uri), uri)

    def test_rejects_user_and_password(self):
        with self.assertRaises(ValidationError):
            _ = self.adapter.validate_python(
                "https://user:ghp_secret@github.com/foo/bar.git"
            )

    def test_rejects_password_without_a_username(self):
        with self.assertRaises(ValidationError):
            _ = self.adapter.validate_python(
                "https://:ghp_secret@github.com/foo/bar.git"
            )

    def test_rejects_an_empty_password(self):
        with self.assertRaises(ValidationError):
            _ = self.adapter.validate_python("https://user:@github.com/foo/bar.git")

    def test_rejects_credentials_with_mixed_case_scheme(self):
        with self.assertRaises(ValidationError):
            _ = self.adapter.validate_python(
                "Https://user:ghp_secret@github.com/foo/bar.git"
            )

    def test_a_port_is_not_mistaken_for_a_password(self):
        uri = "https://git.example.com:8443/foo/bar.git"
        self.assertEqual(self.adapter.validate_python(uri), uri)


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
            GenerateRequest(
                repo_uri="https://example.com/foo.git", scope_id="sub-123", q="x"
            )

    def test_first_call_requires_scope_id(self):
        with self.assertRaises(ValidationError):
            GenerateRequest(
                repo_uri="https://example.com/foo.git",
                terraform_providers="azure",
                q="x",
            )

    def test_first_call_rejects_a_blank_scope_id(self):
        with self.assertRaises(ValidationError):
            GenerateRequest(
                repo_uri="https://example.com/foo.git",
                terraform_providers="azure",
                scope_id="",
                q="x",
            )

    def test_rejects_credentials_embedded_in_the_uri(self):
        with self.assertRaises(ValidationError):
            GenerateRequest(
                repo_uri="https://user:ghp_secret@example.com/foo.git",
                terraform_providers="azure",
                scope_id="sub-123",
                q="x",
            )

    def test_accepts_a_uri_that_only_carries_a_username(self):
        uri = "https://InditexData@dev.azure.com/InditexData/DevOpsv2/_git/repo"
        req = GenerateRequest(
            repo_uri=uri,
            terraform_providers="azure",
            scope_id="sub-123",
            q="x",
        )
        self.assertEqual(req.repo_uri, uri)

    def test_iteration_call_without_a_uri_is_unaffected(self):
        req = GenerateRequest(session_id=str(_SID), q="x")
        self.assertIsNone(req.repo_uri)


class TestDriftRequest(unittest.TestCase):
    def test_drift_first_call(self):
        req = DriftRequest(
            repo_uri="https://example.com/foo.git",
            terraform_providers="azure",
            scope_id="sub-123",
            q="check drift",
            is_partial=True,
        )
        self.assertTrue(req.is_partial)
        self.assertEqual(req.q, "check drift")

    def test_drift_defaults_to_full(self):
        req = DriftRequest(
            repo_uri="https://example.com/foo.git",
            terraform_providers="azure",
            scope_id="sub-123",
            q="detect all drift",
        )
        self.assertFalse(req.is_partial)

    def test_partial_with_blank_query_is_rejected(self):
        with self.assertRaises(ValidationError):
            DriftRequest(
                repo_uri="https://example.com/foo.git",
                terraform_providers="azure",
                scope_id="sub-123",
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
