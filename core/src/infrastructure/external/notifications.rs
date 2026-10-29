// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Notifications service client (`contracts/openapi/notifications.v1.yaml`).
//!
//! Nothing here fails a session: a notification is a side effect, never a
//! reason for it to fail. Every entry point logs a warning and returns
//! `None` when the service is disabled, unreachable, or rejects the
//! request. The semantic helpers own one `kind` string and message format
//! each, so kind strings stay centralized here; the audience is the owner
//! plus every user holding a panel role of editor or above.

use serde_json::{Map, Value};
use uuid::Uuid;

use crate::domain::services::user::UserService;
use crate::infrastructure::external::contract::{CallError, call, unexpected_repr};
use crate::shared::config::SystemConfig;
use crate::shared::constants::PanelRole;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Severity {
    Info,
    Warning,
    Error,
    Critical,
}

impl Severity {
    pub fn value(self) -> &'static str {
        match self {
            Severity::Info => "info",
            Severity::Warning => "warning",
            Severity::Error => "error",
            Severity::Critical => "critical",
        }
    }

    pub fn from_value(v: &str) -> Option<Self> {
        match v {
            "info" => Some(Severity::Info),
            "warning" => Some(Severity::Warning),
            "error" => Some(Severity::Error),
            "critical" => Some(Severity::Critical),
            _ => None,
        }
    }
}

#[derive(Clone)]
pub struct NotificationServiceClient {
    cfg: &'static SystemConfig,
    users: UserService,
}

impl NotificationServiceClient {
    pub fn new(cfg: &'static SystemConfig, users: UserService) -> Self {
        Self { cfg, users }
    }

    /// Panel editors and above, plus the session owner, deduplicated and
    /// sorted. Falls back to the owner alone when the users store cannot be
    /// read, so a notification still goes out.
    pub async fn recipients(&self, owner_email: Option<&str>) -> Vec<String> {
        let staff = match self.users.emails_with_panel_role(PanelRole::Editor).await {
            Ok(s) => s,
            Err(e) => {
                tracing::warn!("Failed to resolve notification recipients: {e}");
                Vec::new()
            }
        };
        let mut all: std::collections::BTreeSet<String> = staff.into_iter().collect();
        if let Some(owner) = owner_email.filter(|o| !o.is_empty()) {
            all.insert(owner.to_string());
        }
        all.into_iter().collect()
    }

    /// Submit a notification; its delivery id, or `None`.
    #[allow(clippy::too_many_arguments)]
    pub async fn notify(
        &self,
        kind: &str,
        severity: Severity,
        subject: &str,
        body: &str,
        audience: &[String],
        links: Option<&[(String, String)]>,
        context: Option<&Map<String, Value>>,
    ) -> Option<Uuid> {
        let cfg = &self.cfg.services.notifications;
        if !cfg.enabled || cfg.endpoint.is_empty() {
            return None;
        }
        let mut request = Map::new();
        request.insert("kind".into(), Value::String(kind.into()));
        request.insert("severity".into(), Value::String(severity.value().into()));
        request.insert("subject".into(), Value::String(subject.into()));
        request.insert("body".into(), Value::String(body.into()));
        request.insert(
            "audience".into(),
            Value::Array(audience.iter().map(|a| Value::String(a.clone())).collect()),
        );
        if let Some(links) = links.filter(|l| !l.is_empty()) {
            request.insert(
                "links".into(),
                Value::Array(
                    links
                        .iter()
                        .map(|(label, url)| serde_json::json!({"label": label, "url": url}))
                        .collect(),
                ),
            );
        }
        if let Some(ctx) = context.filter(|c| !c.is_empty()) {
            request.insert("context".into(), Value::Object(ctx.clone()));
        }
        let request = Value::Object(request);

        let resp = match call(
            reqwest::Method::POST,
            &cfg.endpoint,
            &cfg.token(),
            cfg.timeout,
            "/v1/notify",
            Some(&request),
        )
        .await
        {
            Ok(r) => r,
            Err(CallError::Timeout(e)) | Err(CallError::Request(e)) => {
                tracing::warn!("Failed to send '{kind}' notification ({subject}): {e}");
                return None;
            }
        };
        if resp.status == 202 {
            let parsed = resp
                .json()
                .ok()
                .and_then(|v| v.get("delivery_id").and_then(Value::as_str).map(str::to_string))
                .and_then(|s| Uuid::parse_str(&s).ok());
            return match parsed {
                Some(id) => Some(id),
                None => {
                    tracing::warn!("Failed to send '{kind}' notification ({subject}): invalid delivery_id");
                    None
                }
            };
        }
        tracing::warn!(
            "Notifications service rejected '{kind}' ({subject}): {}",
            unexpected_repr(&resp, &[401, 403, 422, 502, 503])
        );
        None
    }

    async fn notify_helper(&self, kind: &str, severity: Severity, subject: String, owner_email: &str, summary: &str) {
        let audience = self.recipients(Some(owner_email)).await;
        let _ = self
            .notify(kind, severity, &subject, summary, &audience, None, None)
            .await;
    }

    pub async fn notify_compliance_failure(&self, session_id: &Uuid, owner_email: &str, summary: &str) {
        self.notify_helper(
            "iac.compliance.failed",
            Severity::Warning,
            format!("Compliance check failed – session {session_id}"),
            owner_email,
            summary,
        )
        .await;
    }

    pub async fn notify_high_impact(&self, session_id: &Uuid, owner_email: &str, summary: &str) {
        self.notify_helper(
            "iac.impact.high",
            Severity::Warning,
            format!("High impact changes detected – session {session_id}"),
            owner_email,
            summary,
        )
        .await;
    }

    pub async fn notify_exception_failure(&self, session_id: &Uuid, owner_email: &str, summary: &str) {
        self.notify_helper(
            "system.exception.failure",
            Severity::Error,
            format!("System Core exception failure – session {session_id}"),
            owner_email,
            summary,
        )
        .await;
    }

    pub async fn notify_apply_failure(&self, session_id: &Uuid, owner_email: &str, summary: &str) {
        self.notify_helper(
            "iac.apply.failure",
            Severity::Error,
            format!("Infrastructure deployment failure – session {session_id}"),
            owner_email,
            summary,
        )
        .await;
    }
}
