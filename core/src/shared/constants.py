# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from enum import Enum, unique


@unique
class LLMProviderPrefix(Enum):
    """Defines the possible provider prefixes (considered) for model_id prefix in LLMProvider (for LiteLLM)"""

    VERTEX_AI = "vertex_ai"
    BEDROCK = "bedrock"
    OPENAI = "openai"
    AZURE = "azure"
    AZURE_AI = "azure_ai"
    GEMINI = "gemini"


@unique
class Embeddings(Enum):
    """(DEPRECATED) All supported embedding models and providers"""

    OPENAI_LARGE_3 = {
        "model": "text-embedding-3-large",
        "output_dimension": 3_072,
        "provider": "openai",
    }
    OPENAI_SMALL_3 = {
        "model": "text-embedding-3-small",
        "output_dimension": 1_536,
        "provider": "openai",
    }


@unique
class TerraformProvider(Enum):
    AZURE = "azure"
    GCP = "gcp"
    AWS = "aws"
    OCI = "oci"
    KUBERNETES = "kubernetes"


@unique
class ReportType(Enum):
    GENERATE = "generate"
    DRIFT = "drift"
    IMPORT = "import"
    APPLY = "apply"


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
    JOKER = "joker"
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
