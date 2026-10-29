// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Authentication configuration and authorization decisions, the mapping
//! passthrough, and user-originated notifications.

use axum::body::Bytes;
use axum::extract::State;
use axum::http::{HeaderMap, StatusCode};
use axum::response::Response;
use serde_json::{Map, Value, json};

use crate::api::deps::current_user;
use crate::api::errors::{ApiError, ApiResult, json_response};
use crate::api::validation::{self as v, EmbeddedBody, Errors, forbid_extra, loc, loc_with, model_body, parse_body};
use crate::application::state::AppState;
use crate::infrastructure::external::authz::AuthzServiceClient;
use crate::infrastructure::external::mapping::MappingServiceClient;
use crate::infrastructure::external::notifications::Severity;
use crate::shared::constants::TerraformProvider;

/// Public OIDC settings the SPA needs before it can log in (deliberately
/// unauthenticated). A blank `issuer_url` means auth is disabled.
pub async fn auth_config(State(state): State<AppState>) -> ApiResult<Response> {
    let oidc = &state.cfg.oidc;
    Ok(json_response(
        StatusCode::OK,
        &json!({
            "issuer_url": oidc.issuer_url,
            "client_id": oidc.client_id,
            "audience": oidc.audience,
            "scope": oidc.scope,
            "artifact_metadata_header_prefix": state.storage.metadata_header_prefix(),
        }),
    ))
}

/// Whether the caller may operate on a cloud project.
pub async fn authorize(State(state): State<AppState>, headers: HeaderMap, body: Bytes) -> ApiResult<Response> {
    let body = parse_body(&headers, &body)?;
    let user = current_user(&state, &headers).await?;
    let mut errs = Errors::default();
    let embedded = EmbeddedBody::new(&body);
    let mut read = |name: &str| {
        embedded
            .field(&mut errs, name)
            .and_then(|x| v::string(&mut errs, &loc(&["body", name]), x, None, None))
    };
    let cloud = read("cloud");
    let project_name = read("project_name");
    let environment = read("environment");
    errs.finish()?;
    let (cloud, project_name, environment) = (
        cloud.expect("validated"),
        project_name.expect("validated"),
        environment.expect("validated"),
    );
    let user_id = user
        .email
        .clone()
        .filter(|e| !e.is_empty())
        .unwrap_or_else(|| user.subject.clone());
    // An enabled but unreachable sidecar surfaces as 502/504, never an allow.
    let result = AuthzServiceClient::new(state.cfg)
        .check(&cloud, &project_name, Some(&environment), Some(&user_id))
        .await?;
    let message = match (&result.reason, result.authorized) {
        (Some(r), _) if !r.is_empty() => r.clone(),
        (_, true) => format!("Authorized on {project_name}"),
        (_, false) => format!("Not authorized on {cloud}/{project_name} ({environment})"),
    };
    Ok(json_response(
        StatusCode::OK,
        &json!({"result": result.authorized, "message": message, "portalUrl": result.portal_url}),
    ))
}

/// Resolve a business identifier into an IaC repository reference.
pub async fn mapping_resolve(State(state): State<AppState>, headers: HeaderMap, body: Bytes) -> ApiResult<Response> {
    let body = parse_body(&headers, &body)?;
    current_user(&state, &headers).await?;
    let mut errs = Errors::default();
    let mut identifier = None;
    let mut provider = None;
    if let Some(obj) = model_body(&mut errs, &body) {
        identifier = match obj.get("identifier") {
            None => {
                errs.push(
                    "missing",
                    &loc(&["body", "identifier"]),
                    "Field required",
                    Value::Object(obj.clone()),
                    None,
                );
                None
            }
            Some(x) => v::string(&mut errs, &loc(&["body", "identifier"]), x, Some(1), Some(1024)),
        };
        if let Some(x) = obj.get("terraform_provider").filter(|x| !x.is_null()) {
            provider = v::enumeration(
                &mut errs,
                &loc(&["body", "terraform_provider"]),
                x,
                TerraformProvider::from_value,
                TerraformProvider::expected(),
            );
        }
        forbid_extra(&mut errs, &loc(&["body"]), obj, &["identifier", "terraform_provider"]);
    }
    errs.finish()?;
    let resolved = MappingServiceClient::new(state.cfg)
        .resolve(&identifier.expect("validated"), provider)
        .await?;
    // FastAPI validated the response against MappingResolveResponse.
    let len = |s: &str| crate::shared::pyfmt::char_len(s);
    let valid = (1..=2048).contains(&len(&resolved.repo_url))
        && (1..=1024).contains(&len(&resolved.identifier))
        && resolved
            .scope_id
            .as_deref()
            .is_none_or(|s| (1..=1024).contains(&len(s)));
    if !valid {
        return Err(ApiError::Internal(
            "mapping response failed MappingResolveResponse validation".into(),
        ));
    }
    Ok(json_response(
        StatusCode::OK,
        &json!({
            "repo_url": resolved.repo_url,
            "identifier": resolved.identifier,
            "terraform_provider": resolved.terraform_provider,
            "scope_id": resolved.scope_id,
        }),
    ))
}

/// Relay a user-originated notification. The audience is derived from the
/// caller and the users store, so the browser cannot pick recipients.
pub async fn submit_notification(
    State(state): State<AppState>,
    headers: HeaderMap,
    body: Bytes,
) -> ApiResult<Response> {
    let body = parse_body(&headers, &body)?;
    let user = current_user(&state, &headers).await?;
    let mut errs = Errors::default();
    let mut kind = None;
    let mut severity = None;
    let mut subject = None;
    let mut text = None;
    let mut links: Vec<(String, String)> = Vec::new();
    let mut context: Map<String, Value> = Map::new();
    if let Some(obj) = model_body(&mut errs, &body) {
        let raw = Value::Object(obj.clone());
        let required_str = |errs: &mut Errors, name: &str, max: usize| match obj.get(name) {
            None => {
                errs.push("missing", &loc(&["body", name]), "Field required", raw.clone(), None);
                None
            }
            Some(x) => v::string(errs, &loc(&["body", name]), x, Some(1), Some(max)),
        };
        kind = required_str(&mut errs, "kind", 128);
        severity = match obj.get("severity") {
            None => {
                errs.push(
                    "missing",
                    &loc(&["body", "severity"]),
                    "Field required",
                    raw.clone(),
                    None,
                );
                None
            }
            Some(x) => match x.as_str().and_then(Severity::from_value) {
                Some(s) => Some(s),
                None => {
                    let expected = "'info', 'warning', 'error' or 'critical'";
                    errs.push(
                        "literal_error",
                        &loc(&["body", "severity"]),
                        format!("Input should be {expected}"),
                        x.clone(),
                        Some(json!({"expected": expected})),
                    );
                    None
                }
            },
        };
        subject = required_str(&mut errs, "subject", 256);
        text = required_str(&mut errs, "body", 16384);
        if let Some(raw_links) = obj.get("links") {
            let l = loc(&["body", "links"]);
            match raw_links {
                Value::Array(items) => {
                    if items.len() > 32 {
                        errs.push(
                            "too_long",
                            &l,
                            format!(
                                "List should have at most 32 items after validation, not {}",
                                items.len()
                            ),
                            raw_links.clone(),
                            Some(json!({"field_type": "List", "max_length": 32, "actual_length": items.len()})),
                        );
                    } else {
                        for (i, item) in items.iter().enumerate() {
                            let mut il = l.clone();
                            il.push(json!(i));
                            let Value::Object(link) = item else {
                                errs.push(
                                    "model_type",
                                    &il,
                                    "Input should be a valid dictionary or instance of NotificationLink",
                                    item.clone(),
                                    Some(json!({"class_name": "NotificationLink"})),
                                );
                                continue;
                            };
                            let label = match link.get("label") {
                                None => {
                                    errs.push("missing", &loc_with(&il, "label"), "Field required", item.clone(), None);
                                    None
                                }
                                Some(x) => v::string(&mut errs, &loc_with(&il, "label"), x, Some(1), Some(128)),
                            };
                            let url = match link.get("url") {
                                None => {
                                    errs.push("missing", &loc_with(&il, "url"), "Field required", item.clone(), None);
                                    None
                                }
                                Some(x) => v::http_url(&mut errs, &loc_with(&il, "url"), x, 2048),
                            };
                            forbid_extra(&mut errs, &il, link, &["label", "url"]);
                            if let (Some(label), Some(url)) = (label, url) {
                                links.push((label, url));
                            }
                        }
                    }
                }
                other => errs.push("list_type", &l, "Input should be a valid list", other.clone(), None),
            }
        }
        if let Some(raw_ctx) = obj.get("context") {
            match raw_ctx {
                Value::Object(m) => context = m.clone(),
                other => errs.push(
                    "dict_type",
                    &loc(&["body", "context"]),
                    "Input should be a valid dictionary",
                    other.clone(),
                    None,
                ),
            }
        }
        forbid_extra(
            &mut errs,
            &loc(&["body"]),
            obj,
            &["kind", "severity", "subject", "body", "links", "context"],
        );
    }
    errs.finish()?;
    if !state.cfg.services.notifications.enabled {
        return Err(ApiError::http(503, "Notifications are disabled."));
    }
    let audience = state.notifications.recipients(user.email.as_deref()).await;
    let delivery = state
        .notifications
        .notify(
            &kind.expect("validated"),
            severity.expect("validated"),
            &subject.expect("validated"),
            &text.expect("validated"),
            &audience,
            if links.is_empty() { None } else { Some(&links) },
            if context.is_empty() { None } else { Some(&context) },
        )
        .await;
    match delivery {
        Some(id) => Ok(json_response(StatusCode::ACCEPTED, &json!({"delivery_id": id}))),
        None => Err(ApiError::http(502, "Notification was not delivered.")),
    }
}
