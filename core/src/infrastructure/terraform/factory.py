# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0


from pathlib import Path

from src.domains.interfaces.terraform_interface import ITerraform
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
        project_root: Path,
    ):
        self.__project_root = project_root

    def get(self) -> ITerraform:
        return Terraform(
            workspace_path=self.__project_root,
        )
