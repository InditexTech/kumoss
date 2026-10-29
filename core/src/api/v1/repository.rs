// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Git repository and pull-request operations.

use std::sync::Arc;

use axum::body::Bytes;
use axum::extract::State;
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use serde_json::json;

use crate::api::deps::{assert_session_access, current_user, require_operation_role};
use crate::api::errors::{ApiError, ApiResult, json_response};
use crate::api::requests::repo_uri_field;
use crate::api::validation::{EmbeddedBody, Errors, loc, parse_body, uuid};
use crate::application::factory::ApplicationFactory;
use crate::application::state::AppState;
use crate::domain::ports::Git;
use crate::infrastructure::telemetry::PhoenixTracer;
use crate::shared::constants::OperationRole;

fn session_id_body(body: &Option<serde_json::Value>) -> ApiResult<uuid::Uuid> {
    let mut errs = Errors::default();
    let embedded = EmbeddedBody::new(body);
    let sid = embedded
        .field(&mut errs, "session_id")
        .and_then(|v| uuid(&mut errs, &loc(&["body", "session_id"]), v));
    errs.finish()?;
    Ok(sid.expect("validated"))
}

/// Merge the session's latest pull request into the default branch.
pub async fn complete_pr(State(state): State<AppState>, headers: HeaderMap, body: Bytes) -> ApiResult<Response> {
    let body = parse_body(&headers, &body)?;
    let user = current_user(&state, &headers).await?;
    require_operation_role(&user, OperationRole::Developer)?;
    let session_id = session_id_body(&body)?;
    assert_session_access(&state, &user, &session_id, true).await?;
    let ctx = state.db.get_session_context(&session_id).await?;
    if state.db.is_session_blocked(&ctx.id).await? {
        return Err(ApiError::http(
            409,
            format!("Session {} is blocked; PR merge is not allowed.", ctx.id),
        ));
    }
    let prs = state.db.get_pull_requests(&session_id).await?;
    let pr = prs.last().expect("get_pull_requests never returns an empty list");
    ApplicationFactory::git_utils(&state, &ctx.repo_uri, None)
        .complete_pr(pr.number)
        .await?;
    Ok(StatusCode::NO_CONTENT.into_response())
}

/// Submit the session's branch as a pull request.
pub async fn create_pr(State(state): State<AppState>, headers: HeaderMap, body: Bytes) -> ApiResult<Response> {
    let body = parse_body(&headers, &body)?;
    let user = current_user(&state, &headers).await?;
    require_operation_role(&user, OperationRole::Developer)?;
    let session_id = session_id_body(&body)?;
    assert_session_access(&state, &user, &session_id, true).await?;
    let ctx = state.db.get_session_context(&session_id).await?;
    let tracer = Arc::new(PhoenixTracer::new(
        state.cfg,
        &ctx.id,
        &ctx.user_id,
        ctx.terraform_prv,
        &ctx.repo_uri,
        ctx.iac_path.as_deref(),
        ctx.operation,
        &ctx.branch_name,
    ));
    let service = ApplicationFactory::pull_request_service(&state, ctx).map_err(|e| ApiError::Internal(e.message))?;
    let dto = tracer.scope(service.create_pr()).await?;
    Ok(json_response(
        StatusCode::CREATED,
        &json!({"id": dto.id, "url": dto.url, "status": dto.status}),
    ))
}

/// Clone the repository and list its Terraform root-module directories.
pub async fn parse_repository(State(state): State<AppState>, headers: HeaderMap, body: Bytes) -> ApiResult<Response> {
    let body = parse_body(&headers, &body)?;
    let user = current_user(&state, &headers).await?;
    require_operation_role(&user, OperationRole::Developer)?;
    let mut errs = Errors::default();
    let embedded = EmbeddedBody::new(&body);
    let repo_uri = embedded
        .field(&mut errs, "repo_uri")
        .and_then(|v| repo_uri_field(&mut errs, &loc(&["body", "repo_uri"]), v));
    errs.finish()?;
    let repo_uri = repo_uri.expect("validated");
    state.workspace.validate_uri(&repo_uri).await?;
    let roots = ApplicationFactory::iac_root_detector(&state)
        .detect_roots(&repo_uri)
        .await?;
    Ok(json_response(StatusCode::OK, &json!({"roots": roots})))
}
