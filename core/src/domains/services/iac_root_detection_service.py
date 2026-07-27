# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.interfaces.iac_root_detector_interface import IIacRootDetector
from src.domains.interfaces.workspace_interface import IWorkspace


class IacRootDetectionService:
    """Validates a repository URI and detects its IaC root modules."""

    def __init__(self, workspace: IWorkspace, detector: IIacRootDetector):
        self.__workspace = workspace
        self.__detector = detector

    async def detect_roots(self, repo_uri: str) -> list[str]:
        await self.__workspace.validate_uri(repo_uri)
        return await self.__detector.detect_roots(repo_uri)
