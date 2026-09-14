# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0


from pathlib import Path

from src.domains.interfaces.terraform_interface import ITerraform
from src.infrastructure.terraform import Terraform
from src.shared.constants import TerraformProvider


class TerraformFactory:
    """Construct an ITerraform service wired to the workspace.

    The OSS path always uses the service-backed terraform service,
    which calls the IaC microservice over HTTP. The service passes the
    workspace path so the IaC service (which runs in a separate process
    or container) can operate on the same files; the shared volume the
    docker-compose stack mounts into both `api` and `iac` makes
    the paths line up. It also passes the session's cloud scope
    (subscription / project / account id) and its terraform provider,
    which the IaC contract requires on every command so the service can
    inject the scope into the engine's environment.
    """

    def __init__(
        self,
        project_root: Path,
        scope_id: str,
        terraform_provider: TerraformProvider,
    ):
        self.__project_root = project_root
        self.__scope_id = scope_id
        self.__terraform_provider = terraform_provider

    def get(self) -> ITerraform:
        return Terraform(
            workspace_path=self.__project_root,
            scope_id=self.__scope_id,
            terraform_provider=self.__terraform_provider,
        )
