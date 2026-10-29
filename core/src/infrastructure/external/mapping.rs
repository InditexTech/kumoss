// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Mapping microservice client (`contracts/openapi/mapping.v1.yaml`).
//!
//! Degrades to the OSS-default identity passthrough when the service is
//! disabled or unconfigured. An enabled service that fails is a fatal
//! request error (502, 504 for timeouts), never a silent fallback that would
//! mask misconfiguration.

use serde_json::{Map, Value};

use crate::infrastructure::external::contract::{CallError, call, unexpected_repr};
use crate::shared::config::SystemConfig;
use crate::shared::constants::TerraformProvider;
use crate::shared::error::{AppError, AppResult};
use crate::shared::pyfmt::{repr_str, repr_value};
use crate::shared::urls::is_https_url;

/// Outcome of resolving an identifier. `terraform_provider` and `scope_id`
/// are best effort: `None` means "unknown, ask the user".
#[derive(Debug, Clone, PartialEq)]
pub struct ResolvedRef {
    pub repo_url: String,
    pub identifier: String,
    pub terraform_provider: Option<TerraformProvider>,
    pub scope_id: Option<String>,
}

pub struct MappingServiceClient {
    cfg: &'static SystemConfig,
}

impl MappingServiceClient {
    pub fn new(cfg: &'static SystemConfig) -> Self {
        Self { cfg }
    }

    pub async fn resolve(
        &self,
        identifier: &str,
        terraform_provider: Option<TerraformProvider>,
    ) -> AppResult<ResolvedRef> {
        let cfg = &self.cfg.services.mapping;
        if !cfg.enabled || cfg.endpoint.is_empty() {
            // Identity passthrough: nothing is guessed about provider or scope.
            return Ok(ResolvedRef {
                repo_url: identifier.into(),
                identifier: identifier.into(),
                terraform_provider,
                scope_id: None,
            });
        }

        let mut body = Map::new();
        body.insert("identifier".into(), Value::String(identifier.into()));
        if let Some(p) = terraform_provider {
            body.insert("terraform_provider".into(), Value::String(p.value().into()));
        }
        let body = Value::Object(body);

        let resp = call(
            reqwest::Method::POST,
            &cfg.endpoint,
            &cfg.token(),
            10.0,
            "/v1/resolve",
            Some(&body),
        )
        .await
        .map_err(|e| match e {
            CallError::Timeout(m) => AppError::new(format!("mapping service timed out: {m}"), 504),
            CallError::Request(m) => AppError::new(format!("mapping service unreachable: {m}"), 502),
        })?;
        let unparseable =
            |e: String| AppError::new(format!("mapping service returned an unparseable response: {e}"), 502);
        if resp.status != 200 {
            if [400, 401, 403, 404, 422, 502].contains(&resp.status) {
                // The generated client decoded these bodies too.
                resp.json()
                    .map_err(|e| unparseable(format!("JSONDecodeError({})", repr_str(&e))))?;
            }
            return Err(AppError::new(
                format!(
                    "mapping service returned an unexpected response: {}",
                    unexpected_repr(&resp, &[401, 403, 404, 422, 502])
                ),
                502,
            ));
        }
        let data = resp
            .json()
            .map_err(|e| unparseable(format!("JSONDecodeError({})", repr_str(&e))))?;
        let required = |k: &str| -> AppResult<String> {
            match data.get(k) {
                Some(Value::String(s)) => Ok(s.clone()),
                Some(other) => Ok(crate::shared::pyfmt::str_value(other)),
                None => Err(unparseable(format!("KeyError({})", repr_str(k)))),
            }
        };
        let repo_url = required("repo_url")?;
        let echoed = required("identifier")?;
        let provider = match data.get("terraform_provider") {
            None | Some(Value::Null) => None,
            Some(Value::String(s)) => match TerraformProvider::from_value(s) {
                Some(p) => Some(p),
                None => {
                    return Err(AppError::new(
                        format!(
                            "mapping service returned an unknown terraform_provider: {}",
                            repr_str(s)
                        ),
                        502,
                    ));
                }
            },
            Some(other) => {
                return Err(AppError::new(
                    format!(
                        "mapping service returned an unknown terraform_provider: {}",
                        repr_value(other)
                    ),
                    502,
                ));
            }
        };
        let scope_id = match data.get("scope_id") {
            None | Some(Value::Null) => None,
            Some(Value::String(s)) => Some(s.clone()),
            Some(other) => Some(crate::shared::pyfmt::str_value(other)),
        };
        if !is_https_url(&repo_url) {
            return Err(AppError::new(
                "mapping service returned a repo_url that is not an https:// URL",
                502,
            ));
        }
        Ok(ResolvedRef {
            repo_url,
            identifier: echoed,
            terraform_provider: provider,
            scope_id,
        })
    }
}
