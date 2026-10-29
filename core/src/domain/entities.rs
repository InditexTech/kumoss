// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

use std::collections::HashSet;
use std::path::PathBuf;

use chrono::{DateTime, Utc};
use indexmap::IndexMap;
use serde_json::{Map, Value};
use uuid::Uuid;

use crate::domain::dto::{ToolCall, ToolDefinition, ToolResult};
use crate::shared::constants::{OperationRole, OperationType, PanelRole, TerraformProvider};
use crate::shared::error::{AppError, AppResult, ErrorKind};
use crate::shared::pyfmt;

// --- conversation history ----------------------------------------------------------

/// The user half of a turn: a message, or the results of the tools the
/// assistant called in the previous turn.
#[derive(Debug, Clone, PartialEq)]
pub enum TurnUser {
    Text(String),
    Results(Vec<ToolResult>),
}

/// The assistant half of a turn: a message, or the tools it called.
#[derive(Debug, Clone, PartialEq)]
pub enum TurnAssistant {
    Text(String),
    Calls(Vec<ToolCall>),
}

impl TurnUser {
    fn is_empty(&self) -> bool {
        match self {
            TurnUser::Text(s) => s.is_empty(),
            TurnUser::Results(r) => r.is_empty(),
        }
    }

    /// `str(turn.user)`.
    pub fn py_str(&self) -> String {
        match self {
            TurnUser::Text(s) => s.clone(),
            TurnUser::Results(results) => {
                let items: Vec<String> = results.iter().map(tool_result_repr).collect();
                format!("[{}]", items.join(", "))
            }
        }
    }
}

impl TurnAssistant {
    fn is_empty(&self) -> bool {
        match self {
            TurnAssistant::Text(s) => s.is_empty(),
            TurnAssistant::Calls(c) => c.is_empty(),
        }
    }

    /// `str(turn.assistant)`.
    pub fn py_str(&self) -> String {
        match self {
            TurnAssistant::Text(s) => s.clone(),
            TurnAssistant::Calls(calls) => {
                let items: Vec<String> = calls
                    .iter()
                    .map(|c| {
                        format!(
                            "ToolCallDTO(id={}, name={}, parameters={})",
                            pyfmt::repr_str(&c.id),
                            pyfmt::repr_str(&c.name),
                            pyfmt::repr_value(&c.parameters)
                        )
                    })
                    .collect();
                format!("[{}]", items.join(", "))
            }
        }
    }
}

fn tool_result_repr(r: &ToolResult) -> String {
    format!(
        "ToolResultDTO(name={}, tool_call_id={}, success={}, result={}, error_message={})",
        pyfmt::repr_str(&r.name),
        pyfmt::repr_str(&r.tool_call_id),
        if r.success { "True" } else { "False" },
        pyfmt::repr_value(&r.result),
        match &r.error_message {
            Some(m) => pyfmt::repr_str(m),
            None => "None".into(),
        }
    )
}

/// A whole turn in a conversation: a user and an assistant message.
#[derive(Debug, Clone, PartialEq)]
pub struct Turn {
    pub user: TurnUser,
    pub assistant: TurnAssistant,
    pub turn_id: String,
}

/// The history of a conversation.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct History {
    turns: Vec<Turn>,
}

impl History {
    pub fn new() -> Self {
        Self::default()
    }

    /// Rebuild from the persisted `[{"user": ..., "assistant": ...}]` form.
    pub fn from_state(initial_state: &Value) -> Self {
        let mut h = History::new();
        if let Value::Array(turns) = initial_state {
            for turn in turns {
                let text = |key: &str| -> Option<String> {
                    match turn.get(key) {
                        None | Some(Value::Null) => None,
                        Some(Value::String(s)) => Some(s.clone()),
                        Some(other) => Some(pyfmt::str_value(other)),
                    }
                };
                match (text("user"), text("assistant")) {
                    (Some(u), Some(a)) => h.append_turn(TurnUser::Text(u), TurnAssistant::Text(a)),
                    _ => tracing::warn!("append_turn empty user or assistant msg, turn skipped"),
                }
            }
        }
        h
    }

    pub fn iter(&self) -> impl Iterator<Item = &Turn> {
        self.turns.iter()
    }

    pub fn len(&self) -> usize {
        self.turns.len()
    }

    pub fn is_empty(&self) -> bool {
        self.turns.is_empty()
    }

    pub fn reset(&mut self) {
        tracing::warn!("History has been reset.");
        self.turns.clear();
    }

    pub fn get_last_turn(&self) -> AppResult<&Turn> {
        self.turns.last().ok_or_else(|| {
            AppError::kind(
                ErrorKind::HistoryLastTurn,
                "History is empty. Last turn cannot be retrieved.",
                500,
            )
        })
    }

    pub fn get_first_turn(&self) -> AppResult<&Turn> {
        self.turns.first().ok_or_else(|| {
            AppError::kind(
                ErrorKind::HistoryFirstTurn,
                "History is empty. First turn cannot be retrieved.",
                500,
            )
        })
    }

    /// Append a turn; an empty user or assistant message skips it.
    pub fn append_turn(&mut self, user: TurnUser, assistant: TurnAssistant) {
        if user.is_empty() || assistant.is_empty() {
            tracing::warn!("append_turn empty user or assistant msg, turn skipped");
            return;
        }
        let turn_id = self.turns.len().to_string();
        self.turns.push(Turn {
            user,
            assistant,
            turn_id,
        });
    }

    pub fn append_text(&mut self, user: impl Into<String>, assistant: impl Into<String>) {
        self.append_turn(TurnUser::Text(user.into()), TurnAssistant::Text(assistant.into()));
    }

    /// The persisted form.
    pub fn serialize(&self) -> Value {
        Value::Array(
            self.turns
                .iter()
                .map(|t| {
                    let mut m = Map::new();
                    m.insert("user".into(), Value::String(t.user.py_str()));
                    m.insert("assistant".into(), Value::String(t.assistant.py_str()));
                    Value::Object(m)
                })
                .collect(),
        )
    }
}

// --- session context ------------------------------------------------------------------

#[derive(Debug, Clone)]
pub struct SessionContext {
    pub id: Uuid,
    pub user_id: String,
    pub round_id: i64,
    pub repo_uri: String,
    pub scope_id: String,
    pub terraform_prv: TerraformProvider,
    pub branch_name: String,
    pub iac_path: Option<String>,
    pub operation: OperationType,
    /// Internal record fed to the LLM. Not part of any public contract.
    pub history: History,
    /// User-facing conversation: one turn per finished round.
    pub chat_history: History,
    call_dir: Option<PathBuf>,
}

impl SessionContext {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        id: Uuid,
        user_id: String,
        round_id: i64,
        repo_uri: String,
        scope_id: String,
        terraform_prv: TerraformProvider,
        branch_name: String,
        iac_path: Option<String>,
        operation: OperationType,
        history: &Value,
        chat_history: &Value,
    ) -> Self {
        Self {
            id,
            user_id,
            round_id,
            repo_uri,
            scope_id,
            terraform_prv,
            branch_name,
            iac_path,
            operation,
            history: History::from_state(history),
            chat_history: History::from_state(chat_history),
            call_dir: None,
        }
    }

    pub fn call_dir(&self) -> PathBuf {
        self.call_dir.clone().expect("call_dir is set before the handler runs")
    }

    pub fn set_call_dir(&mut self, path: PathBuf) {
        self.call_dir = Some(path);
    }
}

/// The session context shared by every service of one run. Python passed
/// one mutable object around; here every access is a short critical
/// section that never spans an await.
#[derive(Clone)]
pub struct SharedSession(std::sync::Arc<std::sync::Mutex<SessionContext>>);

impl SharedSession {
    pub fn new(ctx: SessionContext) -> Self {
        Self(std::sync::Arc::new(std::sync::Mutex::new(ctx)))
    }

    pub fn read<R>(&self, f: impl FnOnce(&SessionContext) -> R) -> R {
        f(&self.0.lock().expect("session lock"))
    }

    pub fn write<R>(&self, f: impl FnOnce(&mut SessionContext) -> R) -> R {
        f(&mut self.0.lock().expect("session lock"))
    }

    pub fn snapshot(&self) -> SessionContext {
        self.read(|c| c.clone())
    }

    pub fn id(&self) -> Uuid {
        self.read(|c| c.id)
    }

    pub fn round_id(&self) -> i64 {
        self.read(|c| c.round_id)
    }

    /// A copy of the internal history as it stands now.
    pub fn history(&self) -> History {
        self.read(|c| c.history.clone())
    }

    pub fn append_history(&self, user: impl Into<String>, assistant: impl Into<String>) {
        let (u, a) = (user.into(), assistant.into());
        self.write(|c| c.history.append_text(u, a));
    }
}

// --- users ----------------------------------------------------------------------------

/// Internal user resolved from an OIDC identity. Identity key is
/// (issuer, subject); a `None` panel role means no admin-panel access.
#[derive(Debug, Clone, PartialEq)]
pub struct User {
    pub id: i64,
    pub issuer: String,
    pub subject: String,
    pub email: Option<String>,
    pub display_name: Option<String>,
    pub operation_role: OperationRole,
    pub panel_role: Option<PanelRole>,
    pub created_at: DateTime<Utc>,
}

// --- tool loop memory --------------------------------------------------------------------

/// Memory of the tool calls executed during a single agent loop.
///
/// The result of every executed call is already in the conversation, so a
/// call identical to an executed one is a duplicate and is not re-run, and
/// a single-use tool is withdrawn once it succeeds. A successful workspace
/// mutation invalidates both.
pub struct ToolLoopState {
    tools: IndexMap<String, ToolDefinition>,
    sentinel: String,
    executed: HashSet<String>,
    withdrawn: HashSet<String>,
}

/// Parameters that describe the call instead of shaping its result.
const NON_SEMANTIC_PARAMS: [&str; 1] = ["explanation"];

impl ToolLoopState {
    pub fn new(tools: &[ToolDefinition], sentinel: &ToolDefinition) -> Self {
        let mut map = IndexMap::new();
        for t in tools {
            map.insert(t.name.clone(), t.clone());
        }
        Self {
            tools: map,
            sentinel: sentinel.name.clone(),
            executed: HashSet::new(),
            withdrawn: HashSet::new(),
        }
    }

    /// Tools still worth offering to the model, in their original order.
    pub fn available_tools(&self) -> Vec<ToolDefinition> {
        self.tools
            .iter()
            .filter(|(name, _)| !self.withdrawn.contains(*name))
            .map(|(_, t)| t.clone())
            .collect()
    }

    pub fn is_duplicate(&self, call: &ToolCall) -> bool {
        self.executed.contains(&Self::signature(call))
    }

    pub fn record(&mut self, call: &ToolCall, result: &ToolResult) {
        let tool = self.tools.get(&call.name).cloned();
        if result.success && tool.as_ref().is_some_and(|t| t.mutates_workspace) {
            self.executed.clear();
            self.withdrawn.clear();
        }
        self.executed.insert(Self::signature(call));
        if let Some(t) = tool
            && result.success
            && t.single_use
            && t.name != self.sentinel
        {
            self.withdrawn.insert(t.name);
        }
    }

    fn signature(call: &ToolCall) -> String {
        let params = match &call.parameters {
            Value::Object(map) => {
                let filtered: Map<String, Value> = map
                    .iter()
                    .filter(|(k, _)| !NON_SEMANTIC_PARAMS.contains(&k.as_str()))
                    .map(|(k, v)| (k.clone(), v.clone()))
                    .collect();
                Value::Object(filtered)
            }
            other => other.clone(),
        };
        pyfmt::json_dumps_sorted(&Value::Array(vec![Value::String(call.name.clone()), params]))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::shared::constants::ToolContext;
    use serde_json::json;

    fn tool(name: &str, single_use: bool, mutates: bool) -> ToolDefinition {
        ToolDefinition {
            name: name.into(),
            description: String::new(),
            parameters: json!({}),
            context: ToolContext::WorkspaceInspection,
            single_use,
            mutates_workspace: mutates,
        }
    }

    fn call(name: &str, params: Value) -> ToolCall {
        ToolCall {
            id: "1".into(),
            name: name.into(),
            parameters: params,
        }
    }

    fn ok(name: &str) -> ToolResult {
        ToolResult {
            name: name.into(),
            tool_call_id: "1".into(),
            success: true,
            result: json!({}),
            error_message: None,
        }
    }

    #[test]
    fn duplicates_ignore_explanation() {
        let read = tool("read_file", false, false);
        let done = tool("task_complete", true, false);
        let mut state = ToolLoopState::new(&[read.clone(), done.clone()], &done);
        let c = call("read_file", json!({"target_file": "a.tf", "explanation": "x"}));
        state.record(&c, &ok("read_file"));
        assert!(state.is_duplicate(&call("read_file", json!({"explanation": "y", "target_file": "a.tf"}))));
        assert!(!state.is_duplicate(&call("read_file", json!({"target_file": "b.tf"}))));
    }

    #[test]
    fn single_use_withdrawn_until_mutation() {
        let diff = tool("diff_history", true, false);
        let write = tool("write_to_file", false, true);
        let done = tool("task_complete", true, false);
        let mut state = ToolLoopState::new(&[diff.clone(), write.clone(), done.clone()], &done);
        state.record(&call("diff_history", json!({})), &ok("diff_history"));
        assert_eq!(state.available_tools().len(), 2);
        state.record(
            &call("write_to_file", json!({"target_file": "a.tf"})),
            &ok("write_to_file"),
        );
        assert_eq!(state.available_tools().len(), 3);
        assert!(!state.is_duplicate(&call("diff_history", json!({}))));
    }

    #[test]
    fn history_roundtrip_and_skips() {
        let mut h = History::new();
        h.append_text("q", "a");
        h.append_text("", "a");
        h.append_text("q2", "");
        assert_eq!(h.len(), 1);
        assert_eq!(h.serialize(), json!([{"user": "q", "assistant": "a"}]));
        let back = History::from_state(&h.serialize());
        assert_eq!(back, h);
    }
}
