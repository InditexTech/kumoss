# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from enum import Enum, unique


@unique
class LLMProvider(Enum):
    """All supported LLM models and providers"""

    HAIKU_BEDROCK = {
        "model_id": "anthropic.claude-3-5-haiku-20241022-v1:0",
        "max_input_tokens": 200_000,
        "max_output_tokens": 8_192,
        "provider": "anthropicBedrock",
        "phoenix_id": "undefined",
    }
    HAIKU_VERTEX = {
        "model_id": "claude-haiku-4-5@20251001",
        "max_input_tokens": 200_000,
        "max_output_tokens": 64_000,
        "provider": "anthropicVertex",
        "region": "europe-west1",
        "phoenix_id": "claude-haiku-4-5-20251001",
    }
    SONNET_BEDROCK = {
        "model_id": "anthropic.claude-sonnet-4-20250514-v1:0",
        "max_input_tokens": 200_000,
        "max_output_tokens": 32_000,
        "provider": "anthropicBedrock",
        "phoenix_id": "claude-4-sonnet-20250514",
    }
    SONNET_VERTEX = {
        "model_id": "claude-sonnet-4-5",
        "max_input_tokens": 1_000_000,
        "max_output_tokens": 64_000,
        "provider": "anthropicVertex",
        "region": "us-east5",
        "phoenix_id": "claude-sonnet-4-5",
    }
    OPUS_BEDROCK = {
        "model_id": "anthropic.claude-3-opus-20240229-v1:0",
        "max_input_tokens": 200_000,
        "max_output_tokens": 4096,
        "provider": "anthropicBedrock",
        "phoenix_id": "claude-3-opus-20240229",
    }
    OPUS_VERTEX = {
        "model_id": "claude-opus-4@20250514",
        "max_input_tokens": 200_000,
        "max_output_tokens": 32_000,
        "provider": "anthropicVertex",
        "phoenix_id": "claude-4-opus-20250514",
    }
    GEMINI_PRO = {
        "model_id": "gemini-2.5-pro",
        "max_input_tokens": 1_048_576,
        "max_output_tokens": 65_535,
        "provider": "google",
        "phoenix_id": "gemini-2.5-pro",
    }
    GEMINI_FLASH = {
        "model_id": "gemini-3-flash-preview",
        "max_input_tokens": 1_048_576,
        "max_output_tokens": 65_535,
        "provider": "google",
        "phoenix_id": "gemini-3-flash-preview",
    }
    GEMINI_FLASH_LITE = {
        "model_id": "gemini-2.5-flash-lite",
        "max_input_tokens": 1_048_576,
        "max_output_tokens": 65_535,
        "provider": "google",
        "phoenix_id": "gemini-2.5-flash-lite",
    }


@unique
class TerraformProvider(Enum):
    AZURE = "azure"
    GCP = "gcp"
    AWS = "aws"
    OCI = "oci"
    K8S = "kubernetes"


@unique
class ReportType(Enum):
    GENERATE = "generate"
    DRIFT = "drift"
    IMPORT = "import"
    APPLY = "apply"


@unique
class OperationType(Enum):
    GENERATE = "generate"
    DRIFT = "drift"
    IMPORT = "import"


@unique
class SessionStatus(Enum):
    """All possible Session states"""

    STARTED = "started"
    FILTERING = "filtering"
    GENERATING = "generating"
    VALIDATING = "validating"
    REPORT = "report"
    COMPLETED = "completed"
    UNCOMPLETED = "uncompleted"
    FAILED = "failed"


@unique
class PromptsLibrary(Enum):
    """Defines all possible base template prompts"""

    # core
    DOMAIN_FILTER = "domain_filter"
    TASK_SPLITTER = "task_splitter"
    PROMPT_COMPOSITOR = "prompt_compositor"
    IAC_GENERATOR = "iac_generator"
    TARGET_GENERATOR = "target_generator"
    PREDICTIVE_TARGET_CALCULATOR = "predictive_target_calculator"
    REPORT_GENERATOR = "report_generator"
    SUPERVISOR = "supervisor"
    # messages
    JOKER = "joker"  # deprecated
    STATUS_UPDATE = "status_update"
    TASK_ACKNOWLEDGE = "task_acknowledge"


@unique
class ToolContext(Enum):
    """Defines different contexts where tools can be used"""

    DOMAIN_FILTERING = "domain_filtering"
    PROMPT_COMPOSITOR = "prompt_compositor"
    TARGET_GENERATOR = "target_generator"
    REPORT_GENERATOR = "report_generator"
    FILE_OPERATIONS = "file_operations"
    WORKSPACE_INSPECTION = "workspace_inspection"
    EXTERNAL_INFORMATION = "external_information"
    TASK_SPLITTER = "task_splitter"
    GENERAL_TASK_COMPLETION = "general_task_completion"


@unique
class GitProviderName(Enum):
    """Defines all the supported git providers"""

    GITHUB = "github.com"
    AZURE_DEVOPS = "dev.azure.com"
    GITLAB = "gitlab.com"


@unique
class ObjectStorageProvider(Enum):
    """Defines all the supported object-storage backends for artifacts."""

    RUSTFS = "rustfs"
    S3 = "s3"
    STORAGE_ACCOUNT = "storage_account"


@unique
class TracerProject(Enum):
    """Defines all possible tracer projects.
    Note: a project in Phoenix is defined as a group of traces
    """

    DEV_TERRAFORM_DAY2 = "dev-terraform-day2"
    DEV_TERRAFORM_DRIFT = "dev-terraform-drift"
    PRE_TERRAFORM_DAY2 = "pre-terraform-day2"
    PRE_TERRAFORM_DRIFT = "pre-terraform-drift"
    PRO_TERRAFORM_DAY2 = "pro-terraform-day2"
    PRO_TERRAFORM_DRIFT = "pro-terraform-drift"


@unique
class ContentType(Enum):
    """Defines all possible content types for artifact updload"""

    TEXT = "text/plain"
    JSON = "application/json"
