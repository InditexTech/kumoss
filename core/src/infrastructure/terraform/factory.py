# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.interfaces.terraform_interface import ITerraform
from src.domains.services.session_service import SessionService
from src.infrastructure.filesystem import FileSystemUtils
from src.infrastructure.terraform import Terraform


class TerraformFactory:
    """Construct an ITerraform service wired to the workspace.

    The OSS path always uses the service-backed terraform service,
    which calls the IaC microservice over HTTP. The service passes the
    workspace path so the IaC service (which runs in a separate process
    or container) can operate on the same files; the shared volume the
    docker-compose stack mounts into both `api` and `iac` makes
    the paths line up.
    """

    def __init__(
        self,
        session_service: SessionService,
        file_utils: FileSystemUtils,
    ):
        self.__session_svc = session_service
        self.__file_utils = file_utils

    def get(self) -> ITerraform:
        return Terraform(
            workspace_path=self.__file_utils.project_root,
            session_service=self.__session_svc,
        )
