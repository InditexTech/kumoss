# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Terraform state backend for the workspaces the core hands to the IaC service.

This renders a ``backend_override.tf`` addressing that same store, into
the workspace, before `init` runs:

Terraform merges ``*_override.tf`` over the rest of the configuration and
it is gitignored.

Static credentials are embedded when the configuration carries them and
omitted when it does not, leaving the engine to resolve them the way any
Terraform backend does — an instance profile, IRSA or a workload
identity on the IaC service's container.

State is keyed by ``project_id`` (see ``TerraformUtils.project_id``):
clone directories are per-call, so two runs of the same project must be
brought together by something that describes the project itself.
"""

from pathlib import Path

from src.infrastructure.exceptions import TerraformBackendError
from src.shared.config import system_config
from src.shared.config.system_config import StorageConfig
from src.shared.constants import ObjectStorageProvider
from src.shared.logger import logging


class TerraformBackend:
    """Writes the state backend of one workspace."""

    _OVERRIDE_FILENAME: str = "backend_override.tf"
    _STATE_FILENAME: str = "terraform.tfstate"

    def __init__(self, project_id: str):
        self.__project_id = project_id
        self.__storage = system_config.storage

    @property
    def state_key(self) -> str:
        return f"{self.__project_id}/{self._STATE_FILENAME}"

    def apply(self, workspace_path: Path) -> None:
        """Write the override into ``workspace_path``.

        Callers decide whether state is managed at all (an empty
        ``storage.state_bucket`` means they never get here); this
        always writes. A failed write raises
        ``TerraformBackendError``: the run would otherwise silently
        fall back to the workspace's own backend and put the state
        somewhere nobody is tracking.
        """
        content = self.__render()
        override = workspace_path / self._OVERRIDE_FILENAME
        try:
            _ = override.write_text(content, encoding="utf-8")
        except OSError as e:
            logging.warning(f"Could not write {override}: {e}")
            raise TerraformBackendError("Error Terraform backend override render.", 500)
        logging.info(
            f"Terraform state: {self.__storage.provider.value} "
            + f"bucket={self.__storage.state_bucket} key={self.state_key}"
        )

    def __render(self) -> str:
        """The override file's contents for the configured provider.

        Always a rendering: an unsupported provider raises
        ``NotImplementedError`` rather than returning nothing.
        """
        cfg = self.__storage
        match cfg.provider:
            case ObjectStorageProvider.RUSTFS:
                return self.__s3_override(cfg, custom_endpoint=True)
            case ObjectStorageProvider.S3:
                return self.__s3_override(cfg, custom_endpoint=False)
            case ObjectStorageProvider.STORAGE_ACCOUNT:
                return self.__azurerm_override(cfg)
            case _:
                raise NotImplementedError()

    def __s3_override(self, cfg: StorageConfig, custom_endpoint: bool) -> str:
        lines = [
            f'    bucket = "{cfg.state_bucket}"',
            f'    key    = "{self.state_key}"',
            f'    region = "{cfg.region}"',
        ]
        if cfg.access_key and cfg.secret_key:
            lines += [
                "",
                f'    access_key = "{cfg.access_key}"',
                f'    secret_key = "{cfg.secret_key}"',
            ]
        if custom_endpoint:
            lines += [
                "",
                "    endpoints = {",
                f'      s3 = "{cfg.endpoint_url}"',
                "    }",
                "",
                "    use_path_style              = true",
                "    skip_credentials_validation = true",
                "    skip_region_validation      = true",
                "    skip_requesting_account_id  = true",
                "    skip_metadata_api_check     = true",
                "    skip_s3_checksum            = true",
                "    use_lockfile                = true",
            ]
        else:
            lines += ["", "    use_lockfile = true"]
        return self.__wrap("s3", lines)

    def __azurerm_override(self, cfg: StorageConfig) -> str:
        lines = [
            f'    storage_account_name = "{cfg.storage_account_name}"',
            f'    container_name       = "{cfg.state_bucket}"',
            f'    key                  = "{self.state_key}"',
        ]
        if cfg.account_key:
            lines.append(f'    access_key           = "{cfg.account_key}"')
        else:
            lines.append("    use_azuread_auth     = true")
        return self.__wrap("azurerm", lines)

    @staticmethod
    def __wrap(backend_type: str, lines: list[str]) -> str:
        body = "\n".join(lines)
        return f'terraform {{\n  backend "{backend_type}" {{\n{body}\n  }}\n}}\n'
