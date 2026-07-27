# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from src.shared.constants import PromptsLibrary, ToolContext


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
    pr_id: int
    status: str


@dataclass
class PromptTemplateDTO:
    type: PromptsLibrary
    prompt: str


class MainHistory(BaseModel):
    user: str
    assistant: str


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


class ComplianceViolation(BaseModel):
    rule_id: str
    severity: Literal["info", "warning", "error", "critical"]
    resource: str | None = None
    message: str
    suggested_fix: str | None = None


class ComplianceContextDTO(BaseModel):
    output_under_check: str | None = None
    rules: str | None = None
    history: list[dict[str, str]] | None = None


class ComplianceCheckReport(BaseModel):
    passed: bool
    violations: list[ComplianceViolation]
    summary: str
    checked_rules: list[str]


class SessionPayloadDTO(BaseModel):
    """DTO for session payloads"""

    id: str
    response: str
    main_history: MainHistory
    full_history: list[dict[str, str]]
    environment: str
    cloud: str
    project: str
    validation: bool
    branch_name: str
    terraform_plan: str | None = None
    terraform_targets: list[str] | None = None
    terraform_report: (
        TerraformPlanReport | TerraformDriftReport | TerraformApplyReport | None
    ) = None
    compliance_report: ComplianceCheckReport | None = None
    pipeline_url: str | None = None
    apply_allowed: bool = True


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
