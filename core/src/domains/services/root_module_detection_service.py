# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.interfaces.root_module_detector_interface import IRootModuleDetector
from src.domains.interfaces.workspace_interface import IWorkspace


class RootModuleDetectionService:
    """Validates a repository URI and detects its Terraform root modules."""

    def __init__(self, workspace: IWorkspace, detector: IRootModuleDetector):
        self.__workspace = workspace
        self.__detector = detector

    async def detect_roots(self, repo_uri: str) -> list[str]:
        await self.__workspace.validate_uri(repo_uri)
        return await self.__detector.detect_roots(repo_uri)
