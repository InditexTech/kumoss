# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""A session's project identifier must resolve to its repository."""

import unittest
from unittest.mock import AsyncMock, patch

from src.api.v1 import terraform as endpoint
from src.application.iac_requests import GenerateRequest
from src.infrastructure.external.mapping_service import ResolvedRef
from src.shared.exceptions import ExceptionHandler

URL = "https://github.com/org/infra.git"
PROJECT = "sistemas-kumoss-rsg-esc1-dev"


def request(project_identifier: str | None) -> GenerateRequest:
    return GenerateRequest(repo_uri=URL, q="x", project_identifier=project_identifier)


class TestCheckProjectIdentifier(unittest.IsolatedAsyncioTestCase):
    def mapper(self, **kwargs) -> AsyncMock:
        resolve = AsyncMock(**kwargs)
        patcher = patch.object(endpoint.MappingServiceClient, "resolve", resolve)
        _ = patcher.start()
        self.addCleanup(patcher.stop)
        return resolve

    async def test_an_identifier_resolving_to_the_repository_passes(self):
        resolve = self.mapper(
            return_value=ResolvedRef(repo_url=URL, identifier=PROJECT)
        )
        await endpoint._check_project_identifier(request(PROJECT))
        resolve.assert_awaited_once_with(PROJECT)

    async def test_an_identifier_resolving_elsewhere_is_422(self):
        _ = self.mapper(
            return_value=ResolvedRef(
                repo_url="https://github.com/org/other.git", identifier=PROJECT
            )
        )
        with self.assertRaises(ExceptionHandler) as ctx:
            await endpoint._check_project_identifier(request(PROJECT))
        self.assertEqual(ctx.exception.error_code, 422)

    async def test_an_unknown_identifier_keeps_the_mappers_error(self):
        _ = self.mapper(side_effect=ExceptionHandler("unknown project", 404))
        with self.assertRaises(ExceptionHandler) as ctx:
            await endpoint._check_project_identifier(request(PROJECT))
        self.assertEqual(ctx.exception.error_code, 404)

    async def test_without_an_identifier_the_mapper_is_not_called(self):
        resolve = self.mapper()
        for none in (None, URL):
            await endpoint._check_project_identifier(request(none))
        resolve.assert_not_awaited()
