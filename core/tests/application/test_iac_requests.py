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
    ImportRequest,
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
                q="x",
            )

    def test_rejects_neither(self):
        with self.assertRaises(ValidationError):
            GenerateRequest(q="x")

    def test_first_call_needs_only_a_repo_uri_and_a_query(self):
        # Providers and scopes come from the root module's manifest, not
        # from the request.
        req = GenerateRequest(repo_uri="https://example.com/foo.git", q="x")
        self.assertIsNone(req.manifest)
        for gone in ("terraform_providers", "scope_id"):
            self.assertNotIn(gone, GenerateRequest.model_fields)

    def test_rejects_credentials_embedded_in_the_uri(self):
        with self.assertRaises(ValidationError):
            GenerateRequest(
                repo_uri="https://user:ghp_secret@example.com/foo.git",
                q="x",
            )

    def test_accepts_a_uri_that_only_carries_a_username(self):
        uri = "https://InditexData@dev.azure.com/InditexData/DevOpsv2/_git/repo"
        req = GenerateRequest(
            repo_uri=uri,
            q="x",
        )
        self.assertEqual(req.repo_uri, uri)

    def test_iteration_call_without_a_uri_is_unaffected(self):
        req = GenerateRequest(session_id=str(_SID), q="x")
        self.assertIsNone(req.repo_uri)

    def test_accepts_root_module_path(self):
        req = GenerateRequest.model_validate(
            {
                "repo_uri": "https://example.com/foo.git",
                "q": "x",
                "root_module_path": "environments/dev",
            }
        )
        self.assertEqual(req.root_module_path, "environments/dev")

    def test_accepts_deprecated_iac_path_alias(self):
        req = GenerateRequest.model_validate(
            {
                "repo_uri": "https://example.com/foo.git",
                "q": "x",
                "iac_path": "environments/dev",
            }
        )
        self.assertEqual(req.root_module_path, "environments/dev")

    def test_deprecated_alias_is_still_validated(self):
        with self.assertRaises(ValidationError):
            GenerateRequest.model_validate(
                {
                    "repo_uri": "https://example.com/foo.git",
                    "q": "x",
                    "iac_path": "../escape",
                }
            )

    def test_iteration_call_rejects_deprecated_alias_too(self):
        with self.assertRaises(ValidationError):
            GenerateRequest.model_validate(
                {"session_id": str(_SID), "q": "x", "iac_path": "envs/dev"}
            )

    def test_first_call_carries_the_project_identifier(self):
        req = GenerateRequest(
            repo_uri="https://example.com/foo.git",
            q="x",
            project_identifier="  foo ",
        )
        self.assertEqual(req.project_identifier, "foo")

    def test_a_project_identifier_that_is_the_uri_is_dropped(self):
        for same in ("https://example.com/foo.git", " https://example.com/foo.git "):
            req = GenerateRequest(
                repo_uri="https://example.com/foo.git", q="x", project_identifier=same
            )
            self.assertIsNone(req.project_identifier)

    def test_a_blank_project_identifier_is_dropped(self):
        req = GenerateRequest(
            repo_uri="https://example.com/foo.git", q="x", project_identifier="   "
        )
        self.assertIsNone(req.project_identifier)

    def test_project_identifier_must_not_embed_a_password(self):
        # It is committed to the repository with the manifest.
        with self.assertRaises(ValidationError):
            GenerateRequest(
                repo_uri="https://example.com/foo.git",
                q="x",
                project_identifier="https://user:ghp_secret@example.com/foo.git",
            )

    def test_iteration_calls_cannot_carry_a_project_identifier(self):
        with self.assertRaises(ValidationError):
            GenerateRequest(session_id=str(_SID), q="x", project_identifier="foo")


class TestDriftRequest(unittest.TestCase):
    def test_drift_first_call(self):
        req = DriftRequest(
            repo_uri="https://example.com/foo.git",
            q="check drift",
            is_partial=True,
        )
        self.assertTrue(req.is_partial)
        self.assertEqual(req.q, "check drift")

    def test_drift_defaults_to_full(self):
        req = DriftRequest(
            repo_uri="https://example.com/foo.git",
            q="detect all drift",
        )
        self.assertFalse(req.is_partial)

    def test_partial_with_blank_query_is_rejected(self):
        with self.assertRaises(ValidationError):
            DriftRequest(
                repo_uri="https://example.com/foo.git",
                is_partial=True,
                q=" ",
            )


class TestImportRequest(unittest.TestCase):
    def test_first_call_needs_no_scope_id(self):
        req = ImportRequest(repo_uri="https://example.com/foo.git", q="import all")
        self.assertFalse(req.is_partial)
        self.assertNotIn("scope_id", ImportRequest.model_fields)

    def test_partial_with_blank_query_is_rejected(self):
        with self.assertRaises(ValidationError):
            ImportRequest(
                repo_uri="https://example.com/foo.git", q=" ", is_partial=True
            )


class TestApplyRequest(unittest.TestCase):
    def test_apply_takes_only_a_session_id(self):
        req = ApplyRequest(session_id=str(_SID))
        self.assertEqual(req.session_id, _SID)

    def test_apply_requires_a_session_id(self):
        with self.assertRaises(ValidationError):
            ApplyRequest()


class TestManifestAnswers(unittest.TestCase):
    FIRST_CALL = {
        "repo_uri": "https://github.com/foo/bar.git",
        "q": "add a bucket",
    }

    def test_first_call_carries_typed_answers(self):
        req = GenerateRequest.model_validate(
            self.FIRST_CALL
            | {
                "manifest": {
                    "variables": [
                        {"name": "region", "value": {"location": "x"}},
                        {"name": "pw", "value": "s3cr3t", "sensitive": True},
                    ],
                    "var_files": ["envs/dev.tfvars"],
                }
            }
        )
        assert req.manifest is not None
        answers = req.manifest.answers()
        self.assertEqual(answers["region"].value, {"location": "x"})
        self.assertIsNone(answers["region"].sensitive)
        self.assertTrue(answers["pw"].sensitive)
        self.assertEqual(req.manifest.var_files, ["envs/dev.tfvars"])
        self.assertNotIn("s3cr3t", repr(req))

    def test_iteration_calls_cannot_carry_answers(self):
        with self.assertRaises(ValidationError):
            _ = GenerateRequest.model_validate(
                {"session_id": str(_SID), "q": "x", "manifest": {"variables": []}}
            )

    def test_answers_carry_scopes_by_provider_type(self):
        req = GenerateRequest.model_validate(
            self.FIRST_CALL
            | {"manifest": {"scopes": {"azurerm": "sub-1", "google": "proj-1"}}}
        )
        assert req.manifest is not None
        self.assertEqual(req.manifest.scopes, {"azurerm": "sub-1", "google": "proj-1"})
        self.assertEqual(
            GenerateRequest.model_validate(
                self.FIRST_CALL | {"manifest": {"variables": []}}
            ).manifest.scopes,
            {},
        )

    def test_scopes_need_provider_type_names_and_non_empty_ids(self):
        for scopes in (
            {"AzureRM": "sub-1"},
            {"azure rm": "sub-1"},
            {"-azurerm": "sub-1"},
            {"azurerm": ""},
            {"azurerm": "x" * 1025},
            {f"p{i}": "x" for i in range(65)},
        ):
            with self.subTest(scopes=list(scopes)[:2]):
                with self.assertRaises(ValidationError):
                    _ = GenerateRequest.model_validate(
                        self.FIRST_CALL | {"manifest": {"scopes": scopes}}
                    )

    def test_answers_are_unique_and_well_named(self):
        for manifest in (
            {"variables": [{"name": "a", "value": 1}, {"name": "a", "value": 2}]},
            {"variables": [{"name": "not a name", "value": 1}]},
            {"variables": [{"name": "a"}]},
            {"unknown": True},
        ):
            with self.subTest(manifest):
                with self.assertRaises(ValidationError):
                    _ = GenerateRequest.model_validate(
                        self.FIRST_CALL | {"manifest": manifest}
                    )
