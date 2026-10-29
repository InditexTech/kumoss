// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Authz microservice client (`contracts/openapi/authz.v1.yaml`).
//!
//! Returns a permissive default when authz is disabled so existing callers
//! keep working; an enabled but unreachable service is a 502/504, never an
//! allow.

use serde_json::{Map, Value};

use crate::infrastructure::external::contract::{CallError, call, unexpected_repr};
use crate::shared::config::SystemConfig;
use crate::shared::error::{AppError, AppResult};

#[derive(Debug, Clone, PartialEq)]
pub struct CheckResult {
    pub authorized: bool,
    pub portal_url: Option<String>,
    pub reason: Option<String>,
}

pub struct AuthzServiceClient {
    cfg: &'static SystemConfig,
}

impl AuthzServiceClient {
    pub fn new(cfg: &'static SystemConfig) -> Self {
        Self { cfg }
    }

    pub async fn check(
        &self,
        cloud: &str,
        project: &str,
        environment: Option<&str>,
        user_id: Option<&str>,
    ) -> AppResult<CheckResult> {
        let cfg = &self.cfg.services.authz;
        if !cfg.enabled || cfg.endpoint.is_empty() {
            tracing::warn!(
                "authz service is disabled or unconfigured; defaulting to authorized=True. Enable services.authz to enforce."
            );
            return Ok(CheckResult {
                authorized: true,
                portal_url: None,
                reason: Some("authz service disabled in system config".into()),
            });
        }

        let mut body = Map::new();
        if let Some(u) = user_id.filter(|s| !s.is_empty()) {
            body.insert("user_id".into(), Value::String(u.into()));
        }
        body.insert("cloud".into(), Value::String(cloud.into()));
        body.insert("project".into(), Value::String(project.into()));
        if let Some(e) = environment.filter(|s| !s.is_empty()) {
            body.insert("environment".into(), Value::String(e.into()));
        }
        let body = Value::Object(body);

        let resp = call(
            reqwest::Method::POST,
            &cfg.endpoint,
            &cfg.token(),
            15.0,
            "/v1/check",
            Some(&body),
        )
        .await
        .map_err(|e| match e {
            CallError::Timeout(m) => AppError::new(format!("authz service timed out: {m}"), 504),
            CallError::Request(m) => AppError::new(format!("authz service unreachable: {m}"), 502),
        })?;

        if resp.status != 200 {
            return Err(AppError::new(
                format!(
                    "authz service returned an unexpected response: {}",
                    unexpected_repr(&resp, &[401, 422, 502])
                ),
                502,
            ));
        }
        let data = resp.json().map_err(AppError::internal)?;
        let authorized = data
            .get("authorized")
            .and_then(Value::as_bool)
            .ok_or_else(|| AppError::missing_key("authorized"))?;
        let text = |k: &str| data.get(k).and_then(Value::as_str).map(str::to_string);
        Ok(CheckResult {
            authorized,
            portal_url: text("portal_url"),
            reason: text("reason"),
        })
    }
}
