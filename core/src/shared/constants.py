# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from enum import Enum, unique


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
    APPLY = "apply"
    COMPLETED = "completed"
    UNCOMPLETED = "uncompleted"
    FAILED = "failed"


@unique
class PromptsLibrary(Enum):
    """Defines all possible base template prompts"""

    # core
    REQUESTS_FILTER = "requests_filter"
    TASK_SPLITTER = "task_splitter"
    PROMPT_COMPOSITOR = "prompt_compositor"
    IAC_GENERATOR = "iac_generator"
    TARGET_GENERATOR = "target_generator"
    REPORT_GENERATOR = "report_generator"
    PR_GENERATOR = "pr_generator"
    COMPLIANCE_CHECKER = "compliance_checker"
    # messages
    STATUS_UPDATE = "status_update"


@unique
class ToolContext(Enum):
    """Defines different contexts where tools can be used"""

    REQUESTS_FILTER = "requests_filter"
    PROMPT_COMPOSITOR = "prompt_compositor"
    TARGET_GENERATOR = "target_generator"
    REPORT_GENERATOR = "report_generator"
    PR_GENERATOR = "pr_generator"
    FILE_OPERATIONS = "file_operations"
    WORKSPACE_INSPECTION = "workspace_inspection"
    EXTERNAL_INFORMATION = "external_information"
    TASK_SPLITTER = "task_splitter"
    GENERAL_TASK_COMPLETION = "general_task_completion"
    COMPLIANCE_CHECK = "compliance_check"


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
class ContentType(Enum):
    """Defines all possible content types for artifact upload"""

    TEXT = "text/plain"
    JSON = "application/json"


@unique
class TracerProject(Enum):
    """Defines all possible tracer projects.
    Note: a project in Phoenix is defined as a group of traces
    """

    DEV_TERRAFORM_DAY2 = "dev-terraform-day2"
    DEV_TERRAFORM_DRIFT = "dev-terraform-drift"
    DEV_TERRAFORM_IMPORT = "dev-terraform-import"
    PRE_TERRAFORM_DAY2 = "pre-terraform-day2"
    PRE_TERRAFORM_DRIFT = "pre-terraform-drift"
    PRE_TERRAFORM_IMPORT = "pre-terraform-import"
    PRO_TERRAFORM_DAY2 = "pro-terraform-day2"
    PRO_TERRAFORM_DRIFT = "pro-terraform-drift"
    PRO_TERRAFORM_IMPORT = "pro-terraform-import"


@unique
class TargetGenerationMode(Enum):
    """Selects the target generator template file: target_{value}_generator.jinja"""

    SESSION = "session"
    PREDICTIVE = "predictive"
    DRIFT = "drift"
