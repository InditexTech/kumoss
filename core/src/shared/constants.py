# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass
from enum import Enum, unique
from typing import Literal

# Deployment tiers; also the Phoenix tags every seeded prompt version gets.
Environment = Literal["development", "staging", "production"]


@unique
class OperationRole(Enum):
    """Operation roles; definition order is the hierarchy."""

    DEVELOPER = "developer"
    DEVOPS = "devops"

    def at_least(self, minimum: "OperationRole") -> bool:
        order = list(type(self))
        return order.index(self) >= order.index(minimum)


@unique
class PanelRole(Enum):
    """Admin-panel roles; definition order is the hierarchy."""

    VIEWER = "viewer"
    EDITOR = "editor"
    ADMIN = "admin"

    def at_least(self, minimum: "PanelRole") -> bool:
        order = list(type(self))
        return order.index(self) >= order.index(minimum)


# Terraform providers are identified by their type name: the last segment
# of their source address (``azurerm`` for ``hashicorp/azurerm``). Any name
# is valid; these are the ones the platform knows more about.


@dataclass(frozen=True)
class ScopeBinding:
    """How a Terraform run is pointed at a provider's scope.

    ``env``: an environment variable the provider reads as a setting.
    ``var``: an input variable the code passes on itself (an OCI
    compartment is a resource argument; an AWS account goes to the
    provider's ``allowed_account_ids``, which refuses any other account).
    """

    kind: Literal["env", "var"]
    name: str


# Providers whose scope (subscription, project, account, compartment) the
# user is asked for once, and how each run is pointed at it. The IaC
# service attaches no meaning to providers: the core turns each scope into
# the ``env`` or ``vars`` of the request (contracts/openapi/iac.v1.yaml,
# "Environment and input variables").
SCOPE_BINDINGS: dict[str, ScopeBinding] = {
    "azurerm": ScopeBinding("env", "ARM_SUBSCRIPTION_ID"),
    "google": ScopeBinding("env", "GOOGLE_PROJECT"),
    "aws": ScopeBinding("var", "aws_account_id"),
    "oci": ScopeBinding("var", "compartment_ocid"),
}
SCOPED_PROVIDERS: frozenset[str] = frozenset(SCOPE_BINDINGS)

# Providers whose scopes the IaC service can list resources of, for import
# (``ScopeResourceIdsRequest.provider`` in the same contract).
DISCOVERABLE_PROVIDERS: frozenset[str] = frozenset({"azurerm", "google", "aws"})


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
    APPLY = "apply"


@unique
class SessionSearchField(Enum):
    """Which session field a sessions-list ``search`` matches."""

    ALL = "all"  # any of the fields below
    QUERY = "query"  # the session's first query
    REPOSITORY = "repository"  # the workspace (repository) URI
    SESSION_ID = "session_id"


@unique
class SessionStatus(Enum):
    """All possible Session states"""

    STARTED = "started"
    FILTERING = "filtering"
    GENERATING = "generating"
    VALIDATING = "validating"
    RECONCILING = "reconciling"
    REPORT = "report"
    APPLY = "apply"
    COMPLETED = "completed"
    UNCOMPLETED = "uncompleted"
    FAILED = "failed"


@unique
class ManifestStatus(Enum):
    """Where a root module's manifest stands against its current configuration."""

    NOT_FOUND = "not_found"  # never configured: no manifest file yet
    UP_TO_DATE = "up_to_date"  # manifest matches the configuration it was built from
    DRIFTED = "drifted"  # the configuration changed since the manifest was written


@unique
class PromptsLibrary(Enum):
    """Defines all possible base template prompts"""

    # core
    REQUESTS_FILTER = "requests_filter"
    TASK_SPLITTER = "task_splitter"
    FILTER_RECONCILIATION = "filter_reconciliation"
    FILTER_DRIFT_EXCEPTIONS = "filter_drift_exceptions"
    PROMPT_COMPOSITOR = "prompt_compositor"
    IAC_GENERATOR = "iac_generator"
    IMPORT_FILTER = "import_filter"
    IMPORT_EXCEPTIONS = "import_exceptions"
    IMPORT_ADDRESSES = "import_addresses"
    TARGET_GENERATOR = "target_generator"
    REPORT_GENERATOR = "report_generator"
    PR_GENERATOR = "pr_generator"
    COMPLIANCE_CHECKER = "compliance_checker"
    # messages
    STATUS_UPDATE = "status_update"
    CHAT_REPLY = "chat_reply"


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
    FILTER_RECONCILIATION = "filter_reconciliation"
    GENERAL_TASK_COMPLETION = "general_task_completion"
    IMPORT_ADDRESSES = "import_addresses"
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
    DRIFT = "drift"
