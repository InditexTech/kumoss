// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Session-scoped bookkeeping: statuses, rounds, and both histories.

use crate::domain::dto::PromptTemplate;
use crate::domain::entities::{History, SharedSession};
use crate::domain::services::database::DatabaseService;
use crate::domain::services::llm::LlmOrchestrationService;
use crate::domain::services::template::{Render, TemplateOrchestrationService};
use crate::shared::constants::SessionStatus;
use crate::shared::error::AppResult;

#[derive(Clone)]
pub struct SessionService {
    llm: LlmOrchestrationService,
    ctx: SharedSession,
    templates: TemplateOrchestrationService,
    db: DatabaseService,
}

impl SessionService {
    pub fn new(
        llm: LlmOrchestrationService,
        ctx: SharedSession,
        templates: TemplateOrchestrationService,
        db: DatabaseService,
    ) -> Self {
        Self {
            llm,
            ctx,
            templates,
            db,
        }
    }

    pub fn templates(&self) -> &TemplateOrchestrationService {
        &self.templates
    }

    /// Record a new status; with a `prompt`, the message shown is the small
    /// model's rewording of `msg`.
    pub async fn update_status(
        &self,
        msg: &str,
        status: SessionStatus,
        prompt: Option<&PromptTemplate>,
        history: Option<&History>,
    ) -> AppResult<String> {
        let id = self.ctx.id();
        tracing::debug!(
            "Session id '{}' has been updated to {}",
            &id.to_string()[..4],
            status.name()
        );
        let msg = match prompt {
            Some(p) => self.llm.generate_text(msg, p, history, false).await?,
            None => msg.to_string(),
        };
        self.db
            .mark_session_status(&id, status, &msg, Some(self.ctx.round_id()))
            .await?;
        Ok(msg)
    }

    /// `update_status` with the status-update prompt over the given history.
    pub async fn update_status_with_llm(
        &self,
        msg: &str,
        status: SessionStatus,
        history: &History,
    ) -> AppResult<String> {
        let prompt = self.templates.render(Render::StatusUpdate).await?;
        self.update_status(msg, status, Some(&prompt), Some(history)).await
    }

    pub async fn next_round(&self, q: &str) -> AppResult<()> {
        let rid = self.db.create_round(&self.ctx.id(), q).await?;
        self.ctx.write(|c| c.round_id = rid);
        Ok(())
    }

    /// Close the round: a user-facing reply joins the chat history (best
    /// effort) and both histories are persisted.
    pub async fn save(&self, query: &str) -> AppResult<()> {
        let history = self.ctx.history();
        match self.chat_reply(&format!("My request was: {query}\n"), &history).await {
            Ok(reply) => {
                let q = query.to_string();
                self.ctx.write(|c| c.chat_history.append_text(q, reply));
            }
            Err(e) if e.kind == crate::shared::error::ErrorKind::Internal => return Err(e),
            Err(_) => {
                tracing::warn!(
                    "chat_reply failed for session {}; saving history without a chat turn",
                    &self.ctx.id().to_string()[..4]
                );
            }
        }
        let snapshot = self.ctx.snapshot();
        self.db.update_history(&snapshot).await
    }

    /// The user-facing reply, inferred from the internal history alone.
    async fn chat_reply(&self, query: &str, history: &History) -> AppResult<String> {
        let prompt = self.templates.render(Render::ChatReply).await?;
        self.llm.generate_text(query, &prompt, Some(history), false).await
    }
}
