# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel

from src.domains.value_objects.plan_ref import PlanRef
from src.shared.constants import (
    OperationType,
    PromptsLibrary,
    ReportType,
    SessionStatus,
    TerraformProvider,
    ToolContext,
)


@dataclass
class LLMMetadata:
    input_tokens: int
    output_tokens: int
    finish_reason: Literal["end_turn", "max_tokens", "content_filter", "tool_use"]
    model: str


@dataclass
class ToolDefinitionDTO:
    """Represents a tool definition loaded from JSON"""

    name: str
    description: str
    parameters: dict[str, Any]
    context: ToolContext


@dataclass
class ToolCallDTO:
    """Represents a tool call request from the LLM"""

    id: str
    name: str
    parameters: dict[str, Any]


@dataclass
class ToolResultDTO:
    """Represents the result of executing a tool"""

    name: str
    tool_call_id: str
    success: bool
    result: Any
    error_message: str | None = None


@dataclass
class LLMResponseDTO:
    """Enhanced response that can contain both text and tool calls"""

    text: str
    metadata: LLMMetadata
    tool_calls: list[ToolCallDTO]
    thinking: str | None = None

    @classmethod
    def empty(cls):
        return cls(
            text="",
            metadata=LLMMetadata(
                input_tokens=0,
                output_tokens=0,
                finish_reason="end_turn",
                model="undefined",
            ),
            tool_calls=[],
        )


class ValidationResultDTO(Protocol):
    """What a generation loop validator answers, whichever step it ran.

    ``feedback`` is what the next generation attempt is asked to fix;
    ``stdout`` and ``targets`` are the plan the attempt was checked with.
    """

    @property
    def ok(self) -> bool: ...

    @property
    def feedback(self) -> str: ...

    @property
    def stdout(self) -> str: ...

    @property
    def targets(self) -> list[str]: ...


@dataclass
class TerraformPlanDTO:
    """Result of an ``init`` → ``validate`` → ``plan`` sequence.

    ``feedback`` is terraform's stderr and never drift. ``stdout`` is the
    plan text and is present even on failure, because a failed plan's
    output is still worth storing as an artifact; ``plan`` is the
    reusable artifact and is None exactly when ``ok`` is False.
    ``targets`` is repeated outside the ref so the failure path, which
    has no ref, still has it.
    """

    ok: bool
    feedback: str
    stdout: str
    targets: list[str]
    plan: "PlanRef | None"

    @property
    def summary(self) -> str:
        return self.stdout if self.ok else self.feedback

    @classmethod
    def empty(cls) -> "TerraformPlanDTO":
        """A result for a loop that never ran: ``max_drift_reports`` can be 0."""
        return cls(
            ok=True,
            feedback="",
            stdout="",
            targets=[],
            plan=None,
        )


@dataclass
class TerraformDriftDTO:
    """Result of reading drift out of a plan artifact.

    Three states, and consumers must tell them apart:

    - ``in_sync=True`` — no drift; ``drift`` and ``feedback`` both empty.
    - ``in_sync=False`` with an empty ``feedback`` — genuine drift, in ``drift``.
    - ``in_sync=False`` with a non-empty ``feedback`` — the read itself
      failed; ``drift`` is empty and ``plan`` is None.

    Keeping stderr in ``feedback`` and drift in ``drift`` is what stops
    terraform's error output from reaching the task splitter as though it
    were drift. ``stdout`` is the plan text the drift was read from.

    ``excluded`` is what the drift exception rules kept out of
    remediation, one note per iteration that excluded something. It is
    defaulted so the terraform adapter's construction sites need not know
    about it: only the drift loop fills it in.
    """

    in_sync: bool
    drift: str
    feedback: str
    stdout: str
    plan: "PlanRef | None"
    excluded: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.in_sync

    @property
    def summary(self) -> str:
        return self.stdout if self.in_sync else self.feedback or self.drift

    @classmethod
    def empty(cls) -> "TerraformDriftDTO":
        """A result for a loop that never ran: ``max_drift_reports`` can be 0."""
        return cls(
            in_sync=False,
            drift="",
            feedback="",
            stdout="",
            plan=None,
        )


@dataclass
class TerraformApplyDTO:
    ok: bool
    stdout: str
    feedback: str

    @property
    def summary(self) -> str:
        return self.stdout if self.ok else self.feedback


@dataclass
class TerraformDiscoveryDTO:
    """Resource IDs an import round can work with, and why when it has none.

    Both reads a round makes answer with this — the Terraform state and
    the cloud scope — and so does the diff between them.

    A discovery query that finds nothing is a normal outcome, so the
    reason rides with the result instead of being raised: ``feedback`` is
    empty only when ``resource_ids`` is usable, and otherwise says which
    dead end was reached — the cloud query failed (carrying its own
    diagnostics), the scope holds nothing importable, or everything in it
    is already managed. The state read has no tolerated failure of its
    own: it either answers with an empty ``feedback`` or raises.

    On the diff, ``excluded`` holds the unmanaged IDs the import exception
    list withheld, so the round can report what it skipped on purpose.
    """

    resource_ids: list[str]
    feedback: str = ""
    excluded: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.feedback

    @property
    def summary(self) -> str:
        return "\n".join(self.resource_ids) if self.ok else self.feedback


@dataclass
class TerraformImportResourceDTO:
    """Result of importing one resource into the Terraform state.

    One resource at a time is what the engine offers, so a round's
    outcome is assembled from these: ``feedback`` is the engine's stderr
    and is what ends up as the rejected attempt's reason, ``stdout`` the
    import's own output.
    """

    ok: bool
    stdout: str
    feedback: str

    @property
    def summary(self) -> str:
        return self.stdout if self.ok else self.feedback


@dataclass(frozen=True)
class TerraformImportAttempt:
    """One resource an import round tried to bring under Terraform management"""

    address: str
    resource_id: str = field(compare=False)
    error: str = field(compare=False, default="")


@dataclass
class TerraformImportDTO:
    """Outcome of an import round, partitioned by result.

    Callers get the split they need instead of the raw per-resource
    results.
    """

    imported: set[TerraformImportAttempt]
    failed: set[TerraformImportAttempt]

    @property
    def ok(self) -> bool:
        return len(self.failed) == 0

    @property
    def feedback(self) -> str:
        return "\n".join([f"- {f}" for f in self.failed])

    @property
    def stdout(self) -> str:
        return str(self.imported) if len(self.imported) > 0 else ""

    @property
    def targets(self) -> list[str]:
        return []

    @classmethod
    def empty(cls) -> "TerraformImportDTO":
        return cls(
            imported=set(),
            failed=set(),
        )


@dataclass
class FilteredOperationsDTO:
    """What a drift exception filter pass kept and what it removed.

    ``excluded`` is the flattened input minus the flattened survivors,
    matched exactly, so an operation the agent trimmed appears on both
    sides: the original here, its remainder in ``kept``. ``explanation``
    is the agent's own account of what it removed and why, and is the
    better source for anything a user reads.
    """

    kept: list[list[str]]
    excluded: list[str]
    explanation: str


@dataclass
class FilteredImportsDTO:
    """Which of a scope's unmanaged resources an import request asks for.

    ``selected`` stays flat, unlike the other filter passes: imports run
    one resource at a time, so there is nothing to group. ``explanation``
    is the agent's own account of the selection and is what a caller
    reports when ``selected`` comes back empty — the request matched
    nothing, which is an outcome rather than a failure.
    """

    selected: list[str]
    explanation: str


@dataclass
class PullRequestDTO:
    id: int
    url: str
    status: str


@dataclass
class PromptTemplateDTO:
    type: PromptsLibrary
    prompt: str


class Summary(BaseModel):
    """High-level summary containing counts of resources to be created, updated, deleted, or recreated"""

    create: int
    update: int
    delete: int
    recreate: int


class ImpactBanner(BaseModel):
    """Banner highlighting the overall impact level"""

    level: Literal["low", "medium", "high"]
    title: str
    description: str


class ImpactPoint(BaseModel):
    """Individual impact point highlighting important consequences of changes"""

    title: str
    description: str


class PotentialImpact(BaseModel):
    """Human-readable analysis of the overall consequences and implications of applying the Terraform plan"""

    banner: ImpactBanner
    summary: str
    bullet_points: list[ImpactPoint]


class DetailedChange(BaseModel):
    """Aggregated change grouping related resources together"""

    name: str
    action: Literal["create", "update", "delete", "recreate"]
    notes: str
    summary: str
    details: str


class CostBreakdown(BaseModel):
    """Fixed monthly cost breakdown for a resource type"""

    resource_type: str
    pricing_model: Literal["fixed", "usage_based", "free"]
    fixed_monthly_cost: float
    notes: str


class EstimatedCosts(BaseModel):
    """Estimation of the total fixed monthly cost introduced by the plan"""

    currency: str
    total_fixed_monthly_cost: float
    introduction_paragraph: str
    breakdown: list[CostBreakdown]


class TerraformPlanReport(BaseModel):
    """
    Comprehensive, human-readable report analyzing a Terraform plan.
    Transforms technical Terraform plan output into an accessible format that explains
    the changes, their impact, and provides both high-level summaries and detailed
    resource-by-resource analysis.
    """

    summary: Summary
    detailed_changes: list[DetailedChange]
    potential_impact: PotentialImpact
    estimated_costs: EstimatedCosts


class TerraformDriftChange(BaseModel):
    """Individual change made to a resource attribute during drift remediation"""

    attribute_modified: str
    change_description: str
    details: list[str] = []
    reason: str


class TerraformDriftResource(BaseModel):
    """Terraform resource that was modified during drift remediation"""

    file_path: str
    resource_address: str
    changes: list[TerraformDriftChange]


class TerraformDriftUnreconciled(BaseModel):
    """Drift the round could not reconcile, left in place involuntarily.

    ``resource_address`` is best-effort: a failed drift read names no
    resource, and the reason is the whole of what can be reported.
    """

    resource_address: str = ""
    reason: str
    details: list[str] = []


class TerraformDriftException(BaseModel):
    """Drift left unreconciled on purpose, covered by a drift exception rule.

    ``rule`` is the rule that covers the change, quoted back from the
    exception filter's own account of what it removed.
    """

    resource_address: str = ""
    change: str
    rule: str


class TerraformDriftReport(BaseModel):
    """
    Structured report summarizing actions taken to remediate Terraform configuration drift.
    Details which files and resources were changed, specific changes made, and remediation reasons.

    The two trailing blocks are optional and empty unless the round left
    drift behind: ``unreconciled_drift`` for what could not be
    reconciled, ``whitelisted_exceptions`` for what the cloud's drift
    exception rules keep out of remediation.
    """

    summary: str
    status: Literal["Succeeded", "Partial", "Failed"]
    remediated_resources: list[TerraformDriftResource]
    unreconciled_drift: list[TerraformDriftUnreconciled] = []
    whitelisted_exceptions: list[TerraformDriftException] = []


class TerraformApplyChange(BaseModel):
    """Individual resource change completed during terraform apply"""

    resource_type: str
    resource_name: str
    action: Literal["created", "updated", "destroyed", "no_change"]
    status: Literal["success", "failed"]
    details: str
    error_message: str | None = None


class TerraformApplySummary(BaseModel):
    """Summary statistics of the apply operation"""

    total_resources: int
    created: int
    updated: int
    destroyed: int
    failed: int


class TerraformApplyReport(BaseModel):
    """
    Comprehensive report analyzing the results of a Terraform apply operation.
    Provides insights into what was actually created, updated, or destroyed,
    including success/failure status and any issues encountered.
    """

    summary: TerraformApplySummary
    status: Literal["Success", "Partial", "Failed"]
    execution_summary: str
    resource_changes: list[TerraformApplyChange]
    recommendations: list[str]


class TerraformImportedResource(BaseModel):
    """Cloud resource an import round tried to bring under Terraform management"""

    resource_address: str
    resource_id: str
    status: Literal["imported", "failed"]
    details: str
    error_message: str | None = None


class TerraformExcludedResource(BaseModel):
    """Unmanaged resource the import exception list withheld on purpose"""

    resource_id: str
    details: str


class TerraformImportSummary(BaseModel):
    """Summary statistics of the import operation"""

    selected: int
    imported: int
    failed: int


class TerraformImportReport(BaseModel):
    """
    Report describing which unmanaged cloud resources were brought under
    Terraform management. Unlike a plan report it describes resources that
    already exist and already cost money: nothing is created, so the value
    is in what is now tracked in state and whether the generated
    configuration matches it.

    ``excluded_resources`` lists what the import exception list withheld:
    skipped on purpose, never attempted, and not counted in ``summary``.
    """

    summary: TerraformImportSummary
    status: Literal["Succeeded", "Partial", "Failed"]
    execution_summary: str
    imported_resources: list[TerraformImportedResource]
    excluded_resources: list[TerraformExcludedResource]
    state_alignment: str
    recommendations: list[str]


Reports = (
    TerraformPlanReport
    | TerraformApplyReport
    | TerraformDriftReport
    | TerraformImportReport
)


class ComplianceViolation(BaseModel):
    rule_id: str
    severity: Literal["info", "warning", "error", "critical"]
    resource: str | None = None
    message: str
    suggested_fix: str | None = None


class ComplianceCheckReport(BaseModel):
    passed: bool
    violations: list[ComplianceViolation]
    summary: str
    checked_rules: list[str]

    @classmethod
    def empty(cls):
        return cls(
            passed=True,
            violations=[],
            summary="",
            checked_rules=[],
        )


@dataclass
class TerraformPlanResource:
    type: str  # tf resource type
    id: str  # tf resource ID
    content: str  # tf plan txt obj


@dataclass
class TerraformPlanParseObject:
    resources: list[TerraformPlanResource]
    count: int


@dataclass
class TerraformPlanParseDTO:
    """DTO for parsed terraform plan results"""

    added: TerraformPlanParseObject
    removed: TerraformPlanParseObject


class StatusEntry(BaseModel):
    """Read model: one status transition in a session's timeline."""

    status: SessionStatus
    message: str | None
    created_at: datetime


class ArtifactRef(BaseModel):
    """Read model: a client-fetchable artifact produced during a round.

    ``id`` is the pk of the typed row (report / plan / code change), not
    the underlying artifacts row.
    """

    id: int
    url: str
    content_type: str | None
    file_size_bytes: int | None
    created_at: datetime


class ReportRef(ArtifactRef):
    """Read model: a report artifact plus its stored report type."""

    type: ReportType


class ComplianceCheckRef(ArtifactRef):
    """Read model: a compliance check artifact plus its verdict."""

    passed: bool


class TerraformPlanRef(ArtifactRef):
    """Read model: a terraform plan artifact plus its resource targets."""

    targets: list[str]


class CodeChangeRef(ArtifactRef):
    """Read model: one generated/modified file artifact."""

    file_name: str


class PullRequestRef(BaseModel):
    """Read model: a pull request opened during a round.

    ``provider`` is the GitProviderName token (e.g. "GITHUB"), not the host.
    ``number`` is the pull request's id at the provider.
    """

    provider: str
    url: str
    number: int


class RoundDetail(BaseModel):
    """Read model: one generation round with its statuses and artifacts."""

    id: int
    number: int
    query: str
    statuses: list[StatusEntry]
    report: ReportRef | None
    compliance: ComplianceCheckRef | None = None
    plan: TerraformPlanRef | None
    code_changes: list[CodeChangeRef]
    pull_requests: list[PullRequestRef]
    created_at: datetime


class WorkspaceRef(BaseModel):
    """Read model: write-once workspace facts of a session."""

    uri: str
    branch: str
    root_path: str | None


class SessionSummary(BaseModel):
    """Read model: a flattened summary of a session for listing endpoints."""

    uuid: UUID
    username: str | None = None
    operation: OperationType
    provider: TerraformProvider
    first_query: str | None
    workspace_uri: str
    current_status: SessionStatus
    in_flight: bool
    is_blocked: bool
    created_at: datetime
    updated_at: datetime


class SessionDetail(SessionSummary):
    """Read model: the full session aggregate for the detail endpoint.

    ``statuses`` is the session's full status timeline across all rounds;
    the same entries also appear inside their round. Pull requests live
    inside their round. ``history`` is populated only when requested via
    ``include_history``.
    """

    workspace: WorkspaceRef
    scope_id: str
    statuses: list[StatusEntry]
    rounds: list[RoundDetail]
    history: list[dict[str, str]] | None = None


class PaginatedSessionSummary(BaseModel):
    """Response envelope: a page of session summaries plus pagination metadata."""

    items: list[SessionSummary]
    total: int
    page: int
    page_size: int
    total_pages: int
