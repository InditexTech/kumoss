// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Tool orchestration: tool lookup by context and sequential execution of
//! the calls an inference requested.

use std::sync::Arc;
use std::time::SystemTime;

use crate::domain::dto::{ToolCall, ToolDefinition, ToolResult};
use crate::domain::entities::ToolLoopState;
use crate::domain::ports::ToolRegistry;
use crate::infrastructure::telemetry;
use crate::shared::constants::ToolContext;
use crate::shared::error::{AppError, AppResult, ErrorKind};

#[derive(Clone)]
pub struct ToolOrchestrationService {
    registry: Arc<dyn ToolRegistry>,
}

impl ToolOrchestrationService {
    pub fn new(registry: Arc<dyn ToolRegistry>) -> Self {
        Self { registry }
    }

    /// The sentinel tool of a context: the only definition it holds.
    pub fn get_sentinel_tool(&self, context: ToolContext) -> AppResult<ToolDefinition> {
        let tools = self.get_available_tools(&[context])?;
        if tools.len() != 1 {
            return Err(AppError::internal(format!(
                "context {} must hold exactly one sentinel tool",
                context.value()
            )));
        }
        Ok(tools.into_iter().next().expect("one tool"))
    }

    /// The tools of every context, in order.
    pub fn get_available_tools(&self, contexts: &[ToolContext]) -> AppResult<Vec<ToolDefinition>> {
        let mut tools = Vec::new();
        for ctx in contexts {
            tools.extend(self.registry.get_available_tools(*ctx)?);
        }
        if tools.is_empty() {
            let listed: Vec<String> = contexts
                .iter()
                .map(|c| format!("<{}: '{}'>", c.py_str(), c.value()))
                .collect();
            return Err(AppError::kind(
                ErrorKind::ToolsDefinitionEmpty,
                format!(
                    "The list of tools definition for contexts=[{}] cannot be empty",
                    listed.join(", ")
                ),
                400,
            ));
        }
        Ok(tools)
    }

    /// Execute the calls in order. A call identical to one the loop already
    /// executed is rejected instead of run: its result is already in the
    /// conversation, and repeating it only burns the loop budget.
    pub async fn execute_tool_calls(
        &self,
        calls: &[ToolCall],
        mut loop_state: Option<&mut ToolLoopState>,
    ) -> Vec<ToolResult> {
        let mut results = Vec::new();
        for call in calls {
            if let Some(state) = loop_state.as_deref()
                && state.is_duplicate(call)
            {
                tracing::warn!("Rejected duplicate tool call {}", call.name);
                results.push(ToolResult {
                        name: call.name.clone(),
                        tool_call_id: call.id.clone(),
                        success: false,
                        result: serde_json::Value::Null,
                        error_message: Some(format!(
                            "Duplicate call: this exact {} call was already made and its result is already in the conversation above; repeating it cannot return anything new. Act on the information you have: write the files, or call task_complete explaining what blocks you.",
                            call.name
                        )),
                    });
                continue;
            }
            match self.execute_single_tool(call).await {
                Ok(result) => {
                    if let Some(state) = loop_state.as_deref_mut() {
                        state.record(call, &result);
                    }
                    results.push(result);
                }
                Err(e) => {
                    tracing::error!("Tool {} failed: {}", call.name, e.message);
                    results.push(ToolResult {
                        name: call.name.clone(),
                        tool_call_id: call.id.clone(),
                        success: false,
                        result: serde_json::Value::Null,
                        error_message: Some(e.message),
                    });
                }
            }
        }
        results
    }

    async fn execute_single_tool(&self, call: &ToolCall) -> AppResult<ToolResult> {
        let start = SystemTime::now();
        if !self.registry.validate_tool_parameters(&call.name, &call.parameters) {
            return Err(AppError::new(format!("Invalid parameters for tool {}", call.name), 400));
        }
        let result = self.registry.execute_tool(call).await;
        if result.success {
            tracing::debug!("Tool {} executed successfully", call.name);
        } else {
            tracing::warn!(
                "Tool {} failed: {}",
                call.name,
                result.error_message.clone().unwrap_or_default()
            );
        }
        telemetry::trace_tool(start, call, &result);
        Ok(result)
    }
}
