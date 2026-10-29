// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! LLM orchestration: plain text generation, and the tool-calling agent
//! loop that runs until its sentinel tool succeeds.

use std::sync::Arc;

use crate::domain::dto::{PromptTemplate, ToolDefinition, ToolResult};
use crate::domain::entities::{History, ToolLoopState, TurnAssistant, TurnUser};
use crate::domain::ports::{InferenceRequest, LlmProvider};
use crate::domain::services::tools::ToolOrchestrationService;
use crate::infrastructure::telemetry::{self, ChainOutput};
use crate::shared::config::SystemConfig;
use crate::shared::constants::PromptsLibrary;
use crate::shared::error::{AppError, AppResult, ErrorKind};

#[derive(Clone)]
pub struct LlmOrchestrationService {
    main_llm: Arc<dyn LlmProvider>,
    small_llm: Arc<dyn LlmProvider>,
    tool_service: Option<ToolOrchestrationService>,
    cfg: &'static SystemConfig,
}

impl LlmOrchestrationService {
    pub fn new(
        main_llm: Arc<dyn LlmProvider>,
        small_llm: Arc<dyn LlmProvider>,
        tool_service: Option<ToolOrchestrationService>,
        cfg: &'static SystemConfig,
    ) -> Self {
        Self {
            main_llm,
            small_llm,
            tool_service,
            cfg,
        }
    }

    /// A plain text answer from the small model, no tools.
    pub async fn generate_text(
        &self,
        query: &str,
        prompt: &PromptTemplate,
        history: Option<&History>,
        thinking: bool,
    ) -> AppResult<String> {
        let span = telemetry::chain_start(prompt.kind.name(), query);
        let user = TurnUser::Text(query.to_string());
        let mut req = InferenceRequest::new(&user);
        req.system_prompt = Some(&prompt.prompt);
        req.history = history;
        req.thinking = thinking;
        let text = self.small_llm.inference(req).await?.text;
        telemetry::chain_end(span, ChainOutput::Text(&text));
        Ok(text)
    }

    /// Orchestrate the model and its tools until the sentinel tool returns a
    /// result. With one tool and no sentinel, that tool is the sentinel.
    /// `history` is read-only: the loop works on its own copy.
    pub async fn generate(
        &self,
        query: &str,
        tools: Vec<ToolDefinition>,
        sentinel_tool: Option<ToolDefinition>,
        prompt: &PromptTemplate,
        history: Option<&History>,
    ) -> AppResult<ToolResult> {
        let span = telemetry::chain_start(prompt.kind.name(), query);
        let result = self.generate_loop(query, tools, sentinel_tool, prompt, history).await?;
        telemetry::chain_end(span, ChainOutput::Tool(&result));
        Ok(result)
    }

    async fn generate_loop(
        &self,
        query: &str,
        tools: Vec<ToolDefinition>,
        sentinel_tool: Option<ToolDefinition>,
        prompt: &PromptTemplate,
        history: Option<&History>,
    ) -> AppResult<ToolResult> {
        let tool_svc = self
            .tool_service
            .as_ref()
            .ok_or_else(|| AppError::internal("generate() needs a tool service"))?;
        if tools.is_empty() {
            return Err(AppError::internal("generate() needs at least one tool"));
        }
        if tools.len() > 1 && sentinel_tool.is_none() {
            return Err(AppError::internal(
                "sentinel_tool is required when multiple tools are provided",
            ));
        }
        let mut local_tools = tools.clone();
        let sentinel = match sentinel_tool {
            None => local_tools[0].clone(),
            Some(s) => {
                local_tools.push(s.clone());
                s
            }
        };
        let mut local_history = history.cloned().unwrap_or_default();
        let mut tools_result = TurnUser::Text(query.to_string());
        let mut total = 0i64;
        let max = self.cfg.orchestration.max_tool_agent_executions;
        let mut loop_state = ToolLoopState::new(&local_tools, &sentinel);
        let no_tool_nudge = format!(
            "You replied without calling a tool, and only tool calls are read. Continue the work with the tools, or call `{}` with your answer if you are done or blocked.",
            sentinel.name
        );
        let mut nudge: Option<String> = None;
        while !Self::sentinel_executed(&sentinel, &tools_result, &local_tools)? {
            if total == max {
                return Err(AppError::kind(
                    ErrorKind::ToolExecutionsExceeded,
                    format!("The total number of tool executions in this chain has reached the limit. Limit={max}"),
                    500,
                ));
            }
            let last_round = total == max - 1;
            let round_tools = if last_round {
                vec![sentinel.clone()]
            } else {
                loop_state.available_tools()
            };
            let notice = if last_round && local_tools.len() > 1 {
                Some(format!(
                    "Tool budget exhausted: this is your last turn and only `{}` is available. Call it now with the best result the work done so far allows, and state anything left unfinished.",
                    sentinel.name
                ))
            } else {
                nudge.clone()
            };
            let response = {
                let mut req = InferenceRequest::new(&tools_result);
                req.tools = Some(&round_tools);
                req.system_prompt = Some(&prompt.prompt);
                req.history = Some(&local_history);
                req.notice = notice.as_deref();
                self.select_model(prompt.kind).inference(req).await?
            };
            let finish = response.metadata.finish_reason.as_deref();
            if finish != Some("tool_use") && finish != Some("end_turn") {
                return Err(AppError::kind(
                    ErrorKind::UnhandledInferenceFinishReason,
                    format!("Error: unexpected finish reason - {}", finish.unwrap_or("None")),
                    500,
                ));
            }
            nudge = None;
            if !response.tool_calls.is_empty() {
                local_history.append_turn(tools_result.clone(), TurnAssistant::Calls(response.tool_calls.clone()));
                tools_result = TurnUser::Results(
                    tool_svc
                        .execute_tool_calls(&response.tool_calls, Some(&mut loop_state))
                        .await,
                );
            } else if !response.text.is_empty() {
                tracing::warn!("Inference without tool calls: {response:?}");
                local_history.append_turn(tools_result.clone(), TurnAssistant::Text(response.text.clone()));
                tools_result = TurnUser::Text(no_tool_nudge.clone());
            } else {
                tracing::warn!("Empty inference: {response:?}");
                nudge = Some(no_tool_nudge.clone());
            }
            total += 1;
        }
        match tools_result {
            TurnUser::Results(mut results) => Ok(results.pop().expect("the sentinel produced a result")),
            TurnUser::Text(_) => unreachable!("the loop only exits on tool results"),
        }
    }

    fn select_model(&self, kind: PromptsLibrary) -> &Arc<dyn LlmProvider> {
        match kind {
            PromptsLibrary::IacGenerator
            | PromptsLibrary::TargetGenerator
            | PromptsLibrary::ReportGenerator
            | PromptsLibrary::TaskSplitter => &self.main_llm,
            _ => &self.small_llm,
        }
    }

    fn sentinel_executed(sentinel: &ToolDefinition, results: &TurnUser, tools: &[ToolDefinition]) -> AppResult<bool> {
        let TurnUser::Results(results) = results else {
            return Ok(false);
        };
        if !tools.iter().any(|t| t.name == sentinel.name) {
            return Err(AppError::kind(
                ErrorKind::SentinelTool,
                format!(
                    "Sentinel tool '{}' is not included in the list of tools definitions",
                    sentinel.name
                ),
                404,
            ));
        }
        Ok(results
            .iter()
            .any(|r| r.name == sentinel.name && result_truthy(&r.result)))
    }
}

/// `if tool.result:` — Python truthiness of the result value.
fn result_truthy(v: &serde_json::Value) -> bool {
    use serde_json::Value;
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64() != Some(0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}
