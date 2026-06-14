# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.domains.interfaces.terraform_validator_interface import ITerraformValidator
from src.domains.services.session_service import SessionService
from src.infrastructure.filesystem.file_system import FileSystemUtils
from src.infrastructure.validators import TerraformServiceValidator


class ValidatorFactory:
    """Construct an ITerraformValidator wired to the workspace.

    The OSS path always uses the service-backed validator, which calls
    the IaC microservice over HTTP. The validator passes the
    workspace path so the service (which runs in a separate process or
    container) can operate on the same files; the shared volume the
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

    def get(self) -> ITerraformValidator:
        return TerraformServiceValidator(
            workspace_path=self.__file_utils.project_root,
            session_service=self.__session_svc,
        )
