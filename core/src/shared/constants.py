# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from enum import Enum, unique


@unique
class ProviderPrefix(Enum):
    """Defines the possible provider prefixes (considered) for model_id prefix in LLMProvider (for LiteLLM)"""

    VERTEX_AI = "vertex_ai"
    BEDROCK = "bedrock"
    OPENAI = "openai"
    AZURE = "azure"
    AZURE_AI = "azure_ai"


@unique
class LLMProvider(Enum):
    """All supported LLM models and providers"""

    ## Anthropic (Vertex Routing: default, Bedrock Routing: commented out)
    CLAUDE_HAIKU = {
        "model_id": "vertex_ai/claude-haiku-4-5@20251001",
        # "model_id": "bedrock/anthropic.claude-3-5-haiku-20241022-v1:0"
        "max_tokens": 64_000,
        "region": "europe-west1",
    }
    CLAUDE_SONNET = {
        "model_id": "vertex_ai/claude-sonnet-4-6",
        # "model_id": "bedrock/anthropic.claude-sonnet-4-20250514-v1:0",
        "max_tokens": 64_000,
        "region": "us-east5",
    }
    CLAUDE_OPUS = {
        "model_id": "vertex_ai/claude-opus-4@20250514",
        # "model_id": "bedrock/anthropic.claude-3-opus-20240229-v1:0",
        # "model_id": "azure_ai/claude-opus-4-1" # For Azure AI Studio (Anthropic) routing
        "max_tokens": 32_000,
    }

    ## Google Gemini (Vertex Routing)
    GEMINI_PRO = {
        "model_id": "vertex_ai/gemini-2.5-pro",
        "max_tokens": 65_535,
    }
    GEMINI_FLASH = {
        "model_id": "vertex_ai/gemini-3-flash-preview",
        "max_tokens": 65_535,
    }
    GEMINI_FLASH_LITE = {
        "model_id": "vertex_ai/gemini-2.5-flash-lite",
        "max_tokens": 65_535,
    }
    ## OpenAI (OpenAI Routing)
    GPT_5 = {
        "model_id": "openai/gpt-5",
        # "model_id": "azure/<your_deployment_name>" # For Azure OpenAI routing
        "max_tokens": 65_535,
    }
    GPT_5_MINI = {
        "model_id": "openai/gpt-5-mini",
        # "model_id": "azure/<your_deployment_name>" # For Azure OpenAI routing
        "max_tokens": 65_535,
    }


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
