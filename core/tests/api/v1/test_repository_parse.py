# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from src.api.deps import get_current_user
from src.domains.entities import User
from src.infrastructure.exceptions import RepositoryUnreachable
from src.infrastructure.external.mapping_service import ResolvedRef
from src.main import app
from src.shared.config import system_config
from src.shared.config.system_config import ServiceConfig
from src.shared.constants import OperationRole
from src.shared.exceptions import ExceptionHandler

_DETECTION = (
    "src.api.v1.repository.ApplicationFactory.get_root_module_detection_service"
)
_MAPPING = "src.api.v1.repository.MappingServiceClient.resolve"


def _mock_service(detect_roots: AsyncMock) -> MagicMock:
    svc = MagicMock()
    svc.detect_roots = detect_roots
    return svc


def _caller() -> User:
    return User(
        id=7,
        issuer="urn:test",
        subject="sub",
        email="dev@example.com",
        display_name="Dev",
        operation_role=OperationRole.DEVELOPER,
        panel_role=None,
        created_at=datetime.now(UTC),
    )


class TestParseRepository(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app.dependency_overrides[get_current_user] = lambda: _caller()
        self.client = TestClient(app)
        # Mapping off: the core takes the input as the repository URL, so
        # these cases exercise the parse route without a sidecar.
        patcher = patch.object(
            system_config.services, "mapping", ServiceConfig(enabled=False)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def asyncTearDown(self):
        app.dependency_overrides.clear()

    def test_parse_returns_roots(self):
        svc = _mock_service(AsyncMock(return_value=["infra/dev", "infra/pro"]))
        with patch(
            "src.api.v1.repository.ApplicationFactory.get_root_module_detection_service",
            return_value=svc,
        ):
            resp = self.client.post(
                "/v1/repository/parse",
                json={"repo_uri": "https://github.com/org/repo.git"},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["roots"], ["infra/dev", "infra/pro"])
        self.assertEqual(body["repo_url"], "https://github.com/org/repo.git")

    def test_parse_empty_repo_returns_empty_list(self):
        svc = _mock_service(AsyncMock(return_value=[]))
        with patch(
            "src.api.v1.repository.ApplicationFactory.get_root_module_detection_service",
            return_value=svc,
        ):
            resp = self.client.post(
                "/v1/repository/parse",
                json={"repo_uri": "https://github.com/org/empty.git"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["roots"], [])

    def test_parse_unreachable_uri_returns_400_with_a_generic_detail(self):
        svc = _mock_service(AsyncMock(side_effect=RepositoryUnreachable(400)))
        with patch(
            "src.api.v1.repository.ApplicationFactory.get_root_module_detection_service",
            return_value=svc,
        ):
            resp = self.client.post(
                "/v1/repository/parse",
                json={"repo_uri": "https://github.com/org/missing.git"},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.json()["detail"],
            "Repository is not reachable or access was denied.",
        )

    def test_parse_clone_failure_returns_502(self):
        svc = _mock_service(
            AsyncMock(side_effect=ExceptionHandler("clone failed", 502))
        )
        with patch(
            "src.api.v1.repository.ApplicationFactory.get_root_module_detection_service",
            return_value=svc,
        ):
            resp = self.client.post(
                "/v1/repository/parse",
                json={"repo_uri": "https://github.com/org/broken.git"},
            )
        self.assertEqual(resp.status_code, 502)
        self.assertIn("clone failed", resp.json()["detail"])

    def test_parse_rejects_credentials_in_the_uri(self):
        svc = _mock_service(AsyncMock(return_value=[]))
        with patch(
            "src.api.v1.repository.ApplicationFactory.get_root_module_detection_service",
            return_value=svc,
        ):
            resp = self.client.post(
                "/v1/repository/parse",
                json={"repo_uri": "https://user:ghp_secret@github.com/org/repo.git"},
            )
        self.assertEqual(resp.status_code, 422)
        svc.detect_roots.assert_not_awaited()

    def test_parse_accepts_a_username_only_uri(self):
        uri = "https://InditexData@dev.azure.com/InditexData/DevOpsv2/_git/repo"
        svc = _mock_service(AsyncMock(return_value=[]))
        with patch(
            "src.api.v1.repository.ApplicationFactory.get_root_module_detection_service",
            return_value=svc,
        ):
            resp = self.client.post("/v1/repository/parse", json={"repo_uri": uri})
        self.assertEqual(resp.status_code, 200)
        svc.detect_roots.assert_awaited_once_with(uri)

    def test_parse_rejects_non_https_uris(self):
        svc = _mock_service(AsyncMock(return_value=[]))
        with patch(
            "src.api.v1.repository.ApplicationFactory.get_root_module_detection_service",
            return_value=svc,
        ):
            for uri in (
                "git@github.com:org/repo.git",
                "ssh://git@github.com/org/repo.git",
                "file:///nonexistent/repo.git",
                "not-a-valid-url",
            ):
                with self.subTest(uri=uri):
                    resp = self.client.post(
                        "/v1/repository/parse", json={"repo_uri": uri}
                    )
                    self.assertEqual(resp.status_code, 422)
        svc.detect_roots.assert_not_awaited()


class TestParseResolvesThroughMapping(unittest.IsolatedAsyncioTestCase):
    """The wizard's input goes through the mapper before anything is cloned."""

    async def asyncSetUp(self):
        app.dependency_overrides[get_current_user] = lambda: _caller()
        self.client = TestClient(app)

    async def asyncTearDown(self):
        app.dependency_overrides.clear()

    def _post(self, identifier: str, *, resolve: AsyncMock, roots: list[str]):
        svc = _mock_service(AsyncMock(return_value=roots))
        with patch(_DETECTION, return_value=svc), patch(_MAPPING, resolve):
            resp = self.client.post(
                "/v1/repository/parse", json={"repo_uri": identifier}
            )
        return resp, svc

    def test_a_repository_name_is_resolved_then_cloned(self):
        url = "https://github.com/MySuperOrg/foo.git"
        resolve = AsyncMock(return_value=ResolvedRef(repo_url=url, identifier="foo"))
        resp, svc = self._post("foo", resolve=resolve, roots=["infra/dev"])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {"repo_url": url, "project_identifier": "foo", "roots": ["infra/dev"]},
        )
        resolve.assert_awaited_once_with("foo")
        svc.detect_roots.assert_awaited_once_with(url)

    def test_input_is_stripped_before_resolving(self):
        url = "https://github.com/MySuperOrg/foo.git"
        resolve = AsyncMock(return_value=ResolvedRef(repo_url=url, identifier="foo"))
        resp, _ = self._post("  foo  ", resolve=resolve, roots=[])
        resolve.assert_awaited_once_with("foo")
        self.assertEqual(resp.json()["project_identifier"], "foo")

    def test_unresolvable_identifier_is_404_with_the_mappers_reason(self):
        resolve = AsyncMock(
            side_effect=ExceptionHandler("set MAPPING_PREFIX_IDENTIFIER", 404)
        )
        resp, svc = self._post("foo", resolve=resolve, roots=[])
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["detail"], "set MAPPING_PREFIX_IDENTIFIER")
        svc.detect_roots.assert_not_awaited()

    def test_mapper_outage_is_passed_on(self):
        for code in (502, 504):
            with self.subTest(code=code):
                resolve = AsyncMock(side_effect=ExceptionHandler("down", code))
                resp, svc = self._post("foo", resolve=resolve, roots=[])
                self.assertEqual(resp.status_code, code)
                svc.detect_roots.assert_not_awaited()

    def test_a_resolved_url_with_credentials_is_rejected(self):
        url = "https://user:ghp_s3cr3t@github.com/org/repo.git"
        resolve = AsyncMock(return_value=ResolvedRef(repo_url=url, identifier="foo"))
        resp, svc = self._post("foo", resolve=resolve, roots=[])
        self.assertEqual(resp.status_code, 422)
        self.assertNotIn("ghp_s3cr3t", resp.text)
        svc.detect_roots.assert_not_awaited()

    def test_pasted_credentials_never_reach_the_mapper(self):
        for url in (
            "https://user:ghp_s3cr3t@github.com/org/repo.git",
            "  https://user:@github.com/org/repo.git  ",
        ):
            with self.subTest(url=url):
                resolve = AsyncMock()
                resp, svc = self._post(url, resolve=resolve, roots=[])
                self.assertEqual(resp.status_code, 422)
                self.assertNotIn("ghp_s3cr3t", resp.text)
                resolve.assert_not_awaited()
                svc.detect_roots.assert_not_awaited()

    def test_an_empty_input_is_rejected_before_resolving(self):
        for value in ("", "   "):
            with self.subTest(value=value):
                resolve = AsyncMock()
                resp, _ = self._post(value, resolve=resolve, roots=[])
                self.assertEqual(resp.status_code, 422)
                resolve.assert_not_awaited()
