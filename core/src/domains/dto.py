# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from src.shared.constants import (
    OperationType,
    PromptsLibrary,
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


@dataclass
class TerraformValidationDTO:
    validation: bool
    feedback: str
    terraform_plan: str
    terraform_targets: list[str]

    @classmethod
    def empty(cls):
        return cls(
            validation=False,
            feedback="",
            terraform_plan="",
            terraform_targets=[],
        )


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
    summary_paragraph: str
    bullet_points: list[ImpactPoint]


class DetailedChange(BaseModel):
    """Aggregated change grouping related resources together"""

    name: str
    action: Literal["create", "update", "delete", "recreate"]
    notes: str
    summary: str
    details: str


class CostBanner(BaseModel):
    """Banner providing a quick summary of estimated costs"""

    summary: str


class CostBreakdownDetails(BaseModel):
    """Structured details for every resource cost breakdown"""

    estimated_cost: str
    additional_details: str


class CostBreakdown(BaseModel):
    """Detailed breakdown of costs by resource type"""

    resource_type: str
    details: CostBreakdownDetails


class EstimatedCosts(BaseModel):
    """Estimation of monthly and hourly costs for new or updated resources"""

    banner: CostBanner
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


class TerraformDriftReport(BaseModel):
    """
    Structured report summarizing actions taken to remediate Terraform configuration drift.
    Details which files and resources were changed, specific changes made, and remediation reasons.
    """

    remediation_summary: str
    status: Literal["Succeeded", "Partial", "Failed"]
    remediated_resources: list[TerraformDriftResource]


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

    apply_summary: TerraformApplySummary
    status: Literal["Success", "Partial", "Failed"]
    execution_summary: str
    resource_changes: list[TerraformApplyChange]
    recommendations: list[str]


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


class TerraformPlanRef(ArtifactRef):
    """Read model: a terraform plan artifact plus its resource targets."""

    targets: list[str]


class CodeChangeRef(ArtifactRef):
    """Read model: one generated/modified file artifact."""

    file_name: str


class PullRequestRef(BaseModel):
    """Read model: a pull request opened during a round.

    ``provider`` is the GitProviderName token (e.g. "GITHUB"), not the host.
    """

    provider: str
    url: str


class RoundDetail(BaseModel):
    """Read model: one generation round with its statuses and artifacts."""

    id: int
    number: int
    statuses: list[StatusEntry]
    report: ArtifactRef | None
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
    inside their round. ``history`` is populated on admin surfaces only.
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

