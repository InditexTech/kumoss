# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import uuid
import tempfile
from pathlib import Path
from typing import Literal

from src.shared.constants import TracerProviderEnum, TemplateProvider, LLMProvider


class Settings:
    # Phoenix/Tracing configuration
    PHOENIX_PROJECT_NAME: TracerProviderEnum = TracerProviderEnum.DEV_TERRAFORM_DRIFT

    # Test session configuration
    SESSION_ID: uuid.UUID = uuid.uuid4()
    USER_ID: str = "test_user@example.com"

    # File system configuration
    UPLOAD_DIR: Path = Path(tempfile.gettempdir())

    # Default project configuration
    DEFAULT_PROJECT_NAME: str = "dcapaiadd"
    DEFAULT_PROJECT_CLOUD: Literal["azure", "gcp"] = "azure"
    DEFAULT_PROJECT_ENV: Literal["dev", "pre", "pro"] = "dev"
    DEFAULT_PROJECT_UID: str = f"{DEFAULT_PROJECT_NAME}_{SESSION_ID}"

    # Provider configuration
    TEMPLATE_PROVIDER: TemplateProvider = TemplateProvider.AZURE
    LLM_PROVIDER: LLMProvider = LLMProvider.GEMINI_FLASH
    LLM_PROVIDER_SMALL: LLMProvider = LLMProvider.GEMINI_FLASH

    # Validation configuration
    VALIDATION_ITERATIONS: int = 3
