# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import uuid
import tempfile
from pathlib import Path
from typing import Literal

from src.shared.constants import TracerProject, TerraformProvider, OperationType


class Settings:
    # Phoenix/Tracing configuration
    PHOENIX_PROJECT_NAME: TracerProject = TracerProject.DEV_TERRAFORM_DRIFT

    # Test session configuration
    SESSION_ID: uuid.UUID = uuid.uuid4()
    USER_ID: str = "test_user@example.com"

    # File system configuration
    UPLOAD_DIR: Path = Path(tempfile.gettempdir())

    # Default project configuration
    DEFAULT_PROJECT_NAME: str = "nebula"
    DEFAULT_PROJECT_CLOUD: Literal["azure", "gcp", "aws", "oci", "kubernetes"] = "azure"
    DEFAULT_PROJECT_ENV: Literal["dev", "pre", "pro"] = "dev"
    DEFAULT_PROJECT_UID: str = f"{DEFAULT_PROJECT_NAME}_{SESSION_ID}"
    DEFAULT_OPERATION: OperationType = OperationType.GENERATE

    # Provider configuration
    TEMPLATE_PROVIDER: TerraformProvider = TerraformProvider.AZURE
    LLM_MODEL: str = "vertex_ai/claude-sonnet-4-6"
    LLM_SMALL_MODEL: str = "vertex_ai/claude-haiku-4-5@20251001"
    LLM_TEMPERATURE: float = 0.1
    LLM_SMALL_TEMPERATURE: float = 0.1
    LLM_MAX_TOKENS: int = 2048
    LLM_SMALL_MAX_TOKENS: int = 1024

    # Validation configuration
    VALIDATION_ITERATIONS: int = 3
