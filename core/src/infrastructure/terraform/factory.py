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
    the paths line up. The session's scope id travels with it: the IaC
    service requires it on every operation and turns it into the
    provider credentials that command runs under.
    """

    def __init__(
        self,
        project_root: Path,
        scope_id: str,
    ):
        self.__project_root = project_root
        self.__scope_id = scope_id

    def get(self) -> ITerraform:
        return Terraform(
            workspace_path=self.__project_root,
            scope_id=self.__scope_id,
        )
