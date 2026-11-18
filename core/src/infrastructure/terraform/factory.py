# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0


from pathlib import Path

from src.domains.interfaces.git_interface import IGit
from src.domains.interfaces.terraform_interface import ITerraform
from src.domains.value_objects import ProviderScope, TerraformInputs
from src.infrastructure.terraform import Terraform
from src.infrastructure.terraform.backend import TerraformBackend


class TerraformFactory:
    """Construct an ITerraform service wired to the workspace.

    This path calls the IaC microservice over HTTP. The service passes the
    workspace path so the IaC service (which runs in a separate process
    or container) can operate on the same files; the shared volume the
    docker-compose stack mounts into both `api` and `iac` makes
    the paths line up.

    ``git`` must be rooted at ``project_root``: it is what fingerprints
    the workspace a plan was produced against, so a git pointed at
    another tree would compare unrelated revisions."""

    def __init__(
        self,
        project_root: Path,
        git: IGit,
        scopes: tuple[ProviderScope, ...],
        project_id: str,
        inputs: TerraformInputs | None = None,
    ):
        self.__project_root = project_root
        self.__inputs = inputs
        self.__git = git
        self.__scopes = scopes
        self.__project_id = project_id

    def get(self) -> ITerraform:
        return Terraform(
            workspace_path=self.__project_root,
            git=self.__git,
            scopes=self.__scopes,
            backend=TerraformBackend(project_id=self.__project_id),
            inputs=self.__inputs,
        )
