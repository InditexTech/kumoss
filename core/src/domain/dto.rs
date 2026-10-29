// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

use chrono::{DateTime, Utc};
use indexmap::IndexMap;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use uuid::Uuid;

use crate::domain::value_objects::PlanRef;
use crate::shared::constants::{
    OperationType, PromptsLibrary, ReportType, SessionStatus, TerraformProvider, ToolContext,
};
use crate::shared::pyfmt::repr_str;
use crate::shared::serde_util::py_datetime;

// --- LLM / tools -------------------------------------------------------------

#[derive(Debug, Clone, PartialEq)]
pub struct LlmMetadata {
    pub input_tokens: i64,
    pub output_tokens: i64,
    /// `end_turn`, `max_tokens`, `content_filter`, `tool_use`, or `None`
    /// for a provider reason with no mapping.
    pub finish_reason: Option<String>,
    pub model: String,
}

/// A tool definition loaded from JSON.
#[derive(Debug, Clone, PartialEq)]
pub struct ToolDefinition {
    pub name: String,
    pub description: String,
    pub parameters: Value,
    pub context: ToolContext,
    /// Harness metadata, never sent to the model: the result does not depend
    /// on the arguments, so the tool is withdrawn once it succeeds (until the
    /// workspace changes).
    pub single_use: bool,
    /// A success invalidates earlier reads of the workspace.
    pub mutates_workspace: bool,
}

/// A tool call request from the LLM.
#[derive(Debug, Clone, PartialEq)]
pub struct ToolCall {
    pub id: String,
    pub name: String,
    pub parameters: Value,
}

impl ToolCall {
    pub fn params(&self) -> &Map<String, Value> {
        static EMPTY: std::sync::LazyLock<Map<String, Value>> = std::sync::LazyLock::new(Map::new);
        self.parameters.as_object().unwrap_or(&EMPTY)
    }
}

/// The result of executing a tool.
#[derive(Debug, Clone, PartialEq)]
pub struct ToolResult {
    pub name: String,
    pub tool_call_id: String,
    pub success: bool,
    pub result: Value,
    pub error_message: Option<String>,
}

impl ToolResult {
    /// `result.get(key)` on a dict result.
    pub fn get(&self, key: &str) -> Option<&Value> {
        self.result.as_object().and_then(|m| m.get(key))
    }

    /// `result[key]`: a missing key is Python's KeyError.
    pub fn require(&self, key: &str) -> crate::shared::error::AppResult<&Value> {
        self.get(key)
            .ok_or_else(|| crate::shared::error::AppError::missing_key(key))
    }
}

/// A response that can contain both text and tool calls.
#[derive(Debug, Clone, PartialEq)]
pub struct LlmResponse {
    pub text: String,
    pub metadata: LlmMetadata,
    pub tool_calls: Vec<ToolCall>,
    pub thinking: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PromptTemplate {
    pub kind: PromptsLibrary,
    pub prompt: String,
}

// --- terraform results ---------------------------------------------------------

/// Result of an `init` → `validate` → `plan` sequence. `feedback` is
/// terraform's stderr; `stdout` the plan text (present even on failure);
/// `plan` the reusable artifact, None exactly when `ok` is false.
#[derive(Debug, Clone, PartialEq)]
pub struct TerraformPlanDto {
    pub ok: bool,
    pub feedback: String,
    pub stdout: String,
    pub targets: Vec<String>,
    pub plan: Option<PlanRef>,
}

impl TerraformPlanDto {
    pub fn summary(&self) -> &str {
        if self.ok { &self.stdout } else { &self.feedback }
    }

    /// A result for a loop that never ran: `max_drift_reports` can be 0.
    pub fn empty() -> Self {
        Self {
            ok: true,
            feedback: String::new(),
            stdout: String::new(),
            targets: Vec::new(),
            plan: None,
        }
    }
}

/// Result of reading drift out of a plan artifact. Three states:
/// in sync; genuine drift (empty `feedback`); a failed read (non-empty
/// `feedback`, empty `drift`, no plan). `excluded` is what the drift
/// exception rules kept out of remediation.
#[derive(Debug, Clone, PartialEq)]
pub struct TerraformDriftDto {
    pub in_sync: bool,
    pub drift: String,
    pub feedback: String,
    pub stdout: String,
    pub plan: Option<PlanRef>,
    pub excluded: Vec<String>,
}

impl TerraformDriftDto {
    pub fn ok(&self) -> bool {
        self.in_sync
    }

    pub fn summary(&self) -> &str {
        if self.in_sync {
            &self.stdout
        } else if !self.feedback.is_empty() {
            &self.feedback
        } else {
            &self.drift
        }
    }

    pub fn empty() -> Self {
        Self {
            in_sync: false,
            drift: String::new(),
            feedback: String::new(),
            stdout: String::new(),
            plan: None,
            excluded: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct TerraformApplyDto {
    pub ok: bool,
    pub stdout: String,
    pub feedback: String,
}

impl TerraformApplyDto {
    pub fn summary(&self) -> &str {
        if self.ok { &self.stdout } else { &self.feedback }
    }
}

/// Resource IDs an import round can work with, and why when it has none.
/// `feedback` is empty only when `resource_ids` is usable.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct TerraformDiscoveryDto {
    pub resource_ids: Vec<String>,
    pub feedback: String,
    pub excluded: Vec<String>,
}

impl TerraformDiscoveryDto {
    pub fn ok(&self) -> bool {
        self.feedback.is_empty()
    }

    pub fn summary(&self) -> String {
        if self.ok() {
            self.resource_ids.join("\n")
        } else {
            self.feedback.clone()
        }
    }
}

/// Result of importing one resource into the Terraform state.
#[derive(Debug, Clone, PartialEq)]
pub struct TerraformImportResourceDto {
    pub ok: bool,
    pub stdout: String,
    pub feedback: String,
}

impl TerraformImportResourceDto {
    pub fn summary(&self) -> &str {
        if self.ok { &self.stdout } else { &self.feedback }
    }
}

/// One resource an import round tried to bring under Terraform management.
/// Identity (equality, set membership) is the `address` alone.
#[derive(Debug, Clone)]
pub struct TerraformImportAttempt {
    pub address: String,
    pub resource_id: String,
    pub listed_id: String,
    pub error: String,
}

impl PartialEq for TerraformImportAttempt {
    fn eq(&self, other: &Self) -> bool {
        self.address == other.address
    }
}

impl TerraformImportAttempt {
    /// The frozen dataclass repr.
    pub fn py_repr(&self) -> String {
        format!(
            "TerraformImportAttempt(address={}, resource_id={}, listed_id={}, error={})",
            repr_str(&self.address),
            repr_str(&self.resource_id),
            repr_str(&self.listed_id),
            repr_str(&self.error)
        )
    }

    /// `dataclasses.asdict`.
    pub fn as_dict(&self) -> Value {
        serde_json::json!({
            "address": self.address,
            "resource_id": self.resource_id,
            "listed_id": self.listed_id,
            "error": self.error,
        })
    }
}

/// A Python `set[TerraformImportAttempt]`: keyed by address, and like a set
/// an `add` of an address already present keeps the original element.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct AttemptSet(IndexMap<String, TerraformImportAttempt>);

impl AttemptSet {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn add(&mut self, attempt: TerraformImportAttempt) {
        self.0.entry(attempt.address.clone()).or_insert(attempt);
    }

    /// `set.update(other)`.
    pub fn update(&mut self, other: &AttemptSet) {
        for a in other.iter() {
            self.add(a.clone());
        }
    }

    /// `set.difference_update(other)`.
    pub fn difference_update(&mut self, other: &AttemptSet) {
        for a in other.iter() {
            self.0.shift_remove(&a.address);
        }
    }

    pub fn iter(&self) -> impl Iterator<Item = &TerraformImportAttempt> {
        self.0.values()
    }

    pub fn len(&self) -> usize {
        self.0.len()
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    pub fn contains(&self, address: &str) -> bool {
        self.0.contains_key(address)
    }

    /// `str(set)`.
    pub fn py_repr(&self) -> String {
        if self.0.is_empty() {
            return "set()".into();
        }
        let items: Vec<String> = self.iter().map(|a| a.py_repr()).collect();
        format!("{{{}}}", items.join(", "))
    }
}

impl FromIterator<TerraformImportAttempt> for AttemptSet {
    fn from_iter<I: IntoIterator<Item = TerraformImportAttempt>>(iter: I) -> Self {
        let mut s = AttemptSet::new();
        for a in iter {
            s.add(a);
        }
        s
    }
}

/// Outcome of an import round, partitioned by result.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct TerraformImportDto {
    pub imported: AttemptSet,
    pub failed: AttemptSet,
}

impl TerraformImportDto {
    pub fn ok(&self) -> bool {
        self.failed.is_empty()
    }

    pub fn feedback(&self) -> String {
        self.failed
            .iter()
            .map(|f| format!("- {}", f.py_repr()))
            .collect::<Vec<_>>()
            .join("\n")
    }

    pub fn stdout(&self) -> String {
        if self.imported.is_empty() {
            String::new()
        } else {
            self.imported.py_repr()
        }
    }

    pub fn empty() -> Self {
        Self::default()
    }
}

/// What a generation loop validator answers, whichever step it ran.
#[derive(Debug, Clone, PartialEq)]
pub enum ValidationResult {
    Plan(TerraformPlanDto),
    Import(TerraformImportDto),
}

impl ValidationResult {
    pub fn ok(&self) -> bool {
        match self {
            ValidationResult::Plan(p) => p.ok,
            ValidationResult::Import(i) => i.ok(),
        }
    }

    pub fn feedback(&self) -> String {
        match self {
            ValidationResult::Plan(p) => p.feedback.clone(),
            ValidationResult::Import(i) => i.feedback(),
        }
    }

    pub fn stdout(&self) -> String {
        match self {
            ValidationResult::Plan(p) => p.stdout.clone(),
            ValidationResult::Import(i) => i.stdout(),
        }
    }

    pub fn targets(&self) -> Vec<String> {
        match self {
            ValidationResult::Plan(p) => p.targets.clone(),
            ValidationResult::Import(_) => Vec::new(),
        }
    }
}

/// What a drift exception filter pass kept and what it removed.
#[derive(Debug, Clone, PartialEq)]
pub struct FilteredOperations {
    pub kept: Vec<Vec<String>>,
    pub excluded: Vec<String>,
    pub explanation: String,
}

/// Which of a scope's unmanaged resources an import request asks for.
#[derive(Debug, Clone, PartialEq)]
pub struct FilteredImports {
    pub selected: Vec<String>,
    pub explanation: String,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct PullRequestDto {
    pub id: i64,
    pub url: String,
    pub status: String,
}

// --- structured reports (typed views of validated tool results) -----------------

#[derive(Debug, Clone, Deserialize)]
pub struct ImpactBanner {
    pub level: String,
    pub title: String,
    pub description: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct PotentialImpact {
    pub banner: ImpactBanner,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TerraformPlanReport {
    pub potential_impact: PotentialImpact,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TerraformApplyReport {
    pub execution_summary: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ComplianceCheckReport {
    pub passed: bool,
    pub summary: String,
}

impl ComplianceCheckReport {
    pub fn empty() -> Self {
        Self {
            passed: true,
            summary: String::new(),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct ReconciliationChange {
    pub description: String,
    pub reverts_session_change: bool,
    pub reason: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ReconciliationVerdict {
    pub index: i64,
    pub changes: Vec<ReconciliationChange>,
    #[serde(default)]
    pub operation: String,
}

impl ReconciliationVerdict {
    pub fn kept(&self) -> Vec<&ReconciliationChange> {
        self.changes.iter().filter(|c| !c.reverts_session_change).collect()
    }

    pub fn removed(&self) -> Vec<&ReconciliationChange> {
        self.changes.iter().filter(|c| c.reverts_session_change).collect()
    }

    /// The operation left once the session's own changes are out of it.
    pub fn reconciled(&self, original: &str) -> Option<String> {
        if self.removed().is_empty() {
            return Some(original.to_string());
        }
        if self.kept().is_empty() {
            return None;
        }
        Some(self.operation.clone())
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct ReconciliationReport {
    pub verdicts: Vec<ReconciliationVerdict>,
}

// --- read models -----------------------------------------------------------------

/// One status transition in a session's timeline.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct StatusEntry {
    pub status: SessionStatus,
    pub message: Option<String>,
    #[serde(with = "py_datetime")]
    pub created_at: DateTime<Utc>,
}

/// A report artifact plus its stored report type.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ReportRef {
    pub id: i64,
    pub url: String,
    pub content_type: Option<String>,
    pub file_size_bytes: Option<i64>,
    #[serde(with = "py_datetime")]
    pub created_at: DateTime<Utc>,
    #[serde(rename = "type")]
    pub report_type: ReportType,
}

/// A compliance check artifact plus its verdict.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ComplianceCheckRef {
    pub id: i64,
    pub url: String,
    pub content_type: Option<String>,
    pub file_size_bytes: Option<i64>,
    #[serde(with = "py_datetime")]
    pub created_at: DateTime<Utc>,
    pub passed: bool,
}

/// A terraform plan artifact plus its resource targets.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct TerraformPlanRef {
    pub id: i64,
    pub url: String,
    pub content_type: Option<String>,
    pub file_size_bytes: Option<i64>,
    #[serde(with = "py_datetime")]
    pub created_at: DateTime<Utc>,
    pub targets: Vec<String>,
}

/// One generated/modified file artifact.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CodeChangeRef {
    pub id: i64,
    pub url: String,
    pub content_type: Option<String>,
    pub file_size_bytes: Option<i64>,
    #[serde(with = "py_datetime")]
    pub created_at: DateTime<Utc>,
    pub file_name: String,
}

/// A pull request opened during a round. `provider` is the
/// GitProviderName token (e.g. "GITHUB"); `number` its id at the provider.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PullRequestRef {
    pub provider: String,
    pub url: String,
    pub number: i64,
}

/// One generation round with its statuses and artifacts.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RoundDetail {
    pub id: i64,
    pub number: i64,
    pub query: String,
    pub statuses: Vec<StatusEntry>,
    pub reports: Vec<ReportRef>,
    pub compliance_checks: Vec<ComplianceCheckRef>,
    pub plans: Vec<TerraformPlanRef>,
    pub code_changes: Vec<CodeChangeRef>,
    pub pull_requests: Vec<PullRequestRef>,
    #[serde(with = "py_datetime")]
    pub created_at: DateTime<Utc>,
}

/// Write-once workspace facts of a session.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct WorkspaceRef {
    pub uri: String,
    pub branch: String,
    pub root_path: Option<String>,
}

/// A flattened summary of a session for listing endpoints.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SessionSummary {
    pub uuid: Uuid,
    #[serde(default)]
    pub username: Option<String>,
    pub operation: OperationType,
    pub provider: TerraformProvider,
    pub first_query: Option<String>,
    pub workspace: WorkspaceRef,
    pub current_status: SessionStatus,
    pub in_flight: bool,
    pub is_blocked: bool,
    #[serde(with = "py_datetime")]
    pub created_at: DateTime<Utc>,
    #[serde(with = "py_datetime")]
    pub updated_at: DateTime<Utc>,
}

/// The admin superset of the session aggregate; the user route drops
/// `history` (see `SessionDetailView`).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AdminSessionDetail {
    pub uuid: Uuid,
    #[serde(default)]
    pub username: Option<String>,
    pub operation: OperationType,
    pub provider: TerraformProvider,
    pub first_query: Option<String>,
    pub workspace: WorkspaceRef,
    pub current_status: SessionStatus,
    pub in_flight: bool,
    pub is_blocked: bool,
    #[serde(with = "py_datetime")]
    pub created_at: DateTime<Utc>,
    #[serde(with = "py_datetime")]
    pub updated_at: DateTime<Utc>,
    pub scope_id: String,
    pub rounds: Vec<RoundDetail>,
    #[serde(default)]
    pub chat_history: Option<Value>,
    #[serde(default)]
    pub history: Option<Value>,
}

/// `SessionDetail`: the user-facing aggregate (no internal history).
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct SessionDetailView<'a> {
    pub uuid: &'a Uuid,
    pub username: &'a Option<String>,
    pub operation: OperationType,
    pub provider: TerraformProvider,
    pub first_query: &'a Option<String>,
    pub workspace: &'a WorkspaceRef,
    pub current_status: SessionStatus,
    pub in_flight: bool,
    pub is_blocked: bool,
    #[serde(with = "py_datetime")]
    pub created_at: DateTime<Utc>,
    #[serde(with = "py_datetime")]
    pub updated_at: DateTime<Utc>,
    pub scope_id: &'a str,
    pub rounds: &'a [RoundDetail],
    pub chat_history: &'a Option<Value>,
}

impl AdminSessionDetail {
    pub fn user_view(&self) -> SessionDetailView<'_> {
        SessionDetailView {
            uuid: &self.uuid,
            username: &self.username,
            operation: self.operation,
            provider: self.provider,
            first_query: &self.first_query,
            workspace: &self.workspace,
            current_status: self.current_status,
            in_flight: self.in_flight,
            is_blocked: self.is_blocked,
            created_at: self.created_at,
            updated_at: self.updated_at,
            scope_id: &self.scope_id,
            rounds: &self.rounds,
            chat_history: &self.chat_history,
        }
    }
}

/// A page of session summaries plus pagination metadata.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct PaginatedSessionSummary {
    pub items: Vec<SessionSummary>,
    pub total: i64,
    pub page: i64,
    pub page_size: i64,
    pub total_pages: i64,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn attempt(address: &str, rid: &str) -> TerraformImportAttempt {
        TerraformImportAttempt {
            address: address.into(),
            resource_id: rid.into(),
            listed_id: rid.into(),
            error: String::new(),
        }
    }

    #[test]
    fn attempt_set_is_keyed_by_address() {
        let mut s = AttemptSet::new();
        s.add(attempt("a.b", "1"));
        s.add(attempt("a.b", "2"));
        assert_eq!(s.len(), 1);
        assert_eq!(s.iter().next().unwrap().resource_id, "1");
        let other: AttemptSet = [attempt("a.b", "9")].into_iter().collect();
        s.difference_update(&other);
        assert!(s.is_empty());
    }

    #[test]
    fn import_dto_text() {
        let mut dto = TerraformImportDto::empty();
        dto.failed.add(attempt("x.y", "id"));
        assert_eq!(
            dto.feedback(),
            "- TerraformImportAttempt(address='x.y', resource_id='id', listed_id='id', error='')"
        );
        assert_eq!(dto.stdout(), "");
        assert!(!dto.ok());
    }

    #[test]
    fn verdict_reconciliation() {
        let v = ReconciliationVerdict {
            index: 1,
            changes: vec![
                ReconciliationChange {
                    description: "a".into(),
                    reverts_session_change: true,
                    reason: "r".into(),
                },
                ReconciliationChange {
                    description: "b".into(),
                    reverts_session_change: false,
                    reason: "r".into(),
                },
            ],
            operation: "rewritten".into(),
        };
        assert_eq!(v.reconciled("orig").as_deref(), Some("rewritten"));
    }
}
