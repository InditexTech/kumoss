// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Session-creating IaC operations (generate, drift, apply, import).
//!
//! Each call resolves (or creates) the session and returns 202 right away;
//! the round runs in the background: clone, handler, history save, status,
//! in-flight release.

use std::path::PathBuf;
use std::sync::Arc;

use axum::body::Bytes;
use axum::extract::State;
use axum::http::{HeaderMap, StatusCode};
use axum::response::Response;
use serde_json::json;

use crate::api::deps::{assert_session_access, current_user, require_operation_role};
use crate::api::errors::{ApiError, ApiResult, json_response};
use crate::api::requests::{IacKind, parse_apply, parse_iac};
use crate::api::validation::parse_body;
use crate::application::factory::ApplicationFactory;
use crate::application::iac_requests::IacRequest;
use crate::application::services::SessionOrchestrationService;
use crate::application::state::AppState;
use crate::domain::entities::{SessionContext, SharedSession, User};
use crate::infrastructure::telemetry::PhoenixTracer;
use crate::shared::constants::{OperationRole, OperationType, SessionStatus};
use crate::shared::error::{AppError, AppResult, ErrorKind};

/// Validate the URI (first call) and resolve to a session context. Calls
/// referencing an existing session are owner-only.
async fn resolve_or_raise(
    state: &AppState,
    request: &IacRequest,
    user: &User,
    operation: Option<OperationType>,
) -> ApiResult<SessionContext> {
    if let Some(sid) = request.session_id() {
        assert_session_access(state, user, &sid, true).await?;
    }
    let resolved: AppResult<SessionContext> = async {
        if let Some(uri) = request.repo_uri() {
            state.workspace.validate_uri(uri).await?;
        }
        SessionOrchestrationService::new(state.db.clone())
            .resolve(request, operation, user.id)
            .await
    }
    .await;
    resolved.map_err(ApiError::from)
}

#[derive(Clone, Copy)]
enum Round {
    Generate,
    Drift { is_partial: bool },
    Apply,
    Import { is_partial: bool },
}

/// The whole background pipeline of one round.
async fn run_round(state: AppState, ctx: SessionContext, round: Round, q: String) {
    let orchestration = SessionOrchestrationService::new(state.db.clone());
    let id = ctx.id;
    if let Err(e) = orchestration.acquire(&id).await {
        // Never got the lock: the session is already running or finished.
        tracing::error!("runner not started: {} (session {id})", e.message);
        return;
    }
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
    let user_id = ctx.user_id.clone();
    let operation = ctx.operation;
    let shared = SharedSession::new(ctx);
    let st = state.clone();
    let sh = shared.clone();
    tracer
        .scope(async move {
            let mut call_dir: Option<PathBuf> = None;
            let outcome: AppResult<()> = async {
                let (repo_uri, branch, iac_path) =
                    sh.read(|c| (c.repo_uri.clone(), c.branch_name.clone(), c.iac_path.clone()));
                let dir = st.workspace.setup_call_dir(&id, &repo_uri, &branch).await?;
                call_dir = Some(dir.clone());
                let root = st.workspace.iac_root(&dir, iac_path.as_deref())?;
                sh.write(|c| c.set_call_dir(root));
                let factory = ApplicationFactory::new(&st, sh.clone());
                match round {
                    Round::Generate => factory.terraform_crud_handler()?.handle(&q).await?,
                    Round::Drift { is_partial } => factory.terraform_drift_handler()?.handle(&q, is_partial).await?,
                    Round::Apply => factory.terraform_apply_handler()?.handle().await?,
                    Round::Import { is_partial } => factory.terraform_import_handler()?.handle(&q, is_partial).await?,
                }
                let last = st.db.get_last_status(&id).await?;
                if last.status != SessionStatus::Uncompleted {
                    st.db.mark_completed(&id, operation.name()).await?;
                }
                Ok(())
            }
            .await;
            match outcome {
                Ok(()) => {}
                Err(e) if e.is(ErrorKind::RequestFilter) => {
                    let reply = sh.read(|c| c.chat_history.get_last_turn().map(|t| t.assistant.py_str()));
                    let marked = match reply {
                        Ok(reply) => st.db.mark_uncompleted(&id, &reply).await,
                        Err(err) => Err(err),
                    };
                    if let Err(err) = marked {
                        tracing::error!("could not mark session {id} uncompleted: {}", err.message);
                    }
                }
                Err(e) => {
                    let msg = format!("runner failed: {}", e.message);
                    tracing::error!("{msg} (session {id})");
                    if let Err(err) = st.db.mark_failed(&id, &msg).await {
                        tracing::error!("could not mark session {id} failed: {}", err.message);
                    }
                    st.notifications.notify_exception_failure(&id, &user_id, &msg).await;
                }
            }
            st.workspace.cleanup(call_dir.as_deref());
            if let Err(e) = orchestration.release(&id).await {
                tracing::error!("could not release session {id}: {}", e.message);
            }
        })
        .await;
}

fn accepted(ctx: &SessionContext) -> Response {
    json_response(StatusCode::ACCEPTED, &json!({"session_id": ctx.id.to_string()}))
}

pub async fn generate(State(state): State<AppState>, headers: HeaderMap, body: Bytes) -> ApiResult<Response> {
    let body = parse_body(&headers, &body)?;
    let user = current_user(&state, &headers).await?;
    require_operation_role(&user, OperationRole::Developer)?;
    let parsed = parse_iac(&body, IacKind::Generate)?;
    let ctx = resolve_or_raise(&state, &parsed.request, &user, Some(OperationType::Generate)).await?;
    tokio::spawn(run_round(
        state.clone(),
        ctx.clone(),
        Round::Generate,
        parsed.request.q().to_string(),
    ));
    Ok(accepted(&ctx))
}

pub async fn drift(State(state): State<AppState>, headers: HeaderMap, body: Bytes) -> ApiResult<Response> {
    let body = parse_body(&headers, &body)?;
    let user = current_user(&state, &headers).await?;
    require_operation_role(&user, OperationRole::Devops)?;
    let parsed = parse_iac(&body, IacKind::Drift)?;
    let ctx = resolve_or_raise(&state, &parsed.request, &user, Some(OperationType::Drift)).await?;
    tokio::spawn(run_round(
        state.clone(),
        ctx.clone(),
        Round::Drift {
            is_partial: parsed.is_partial,
        },
        parsed.request.q().to_string(),
    ));
    Ok(accepted(&ctx))
}

pub async fn apply(State(state): State<AppState>, headers: HeaderMap, body: Bytes) -> ApiResult<Response> {
    let body = parse_body(&headers, &body)?;
    let user = current_user(&state, &headers).await?;
    require_operation_role(&user, OperationRole::Developer)?;
    let request = parse_apply(&body)?;
    let ctx = resolve_or_raise(&state, &request, &user, None).await?;
    let blocked = state
        .db
        .is_session_blocked(&ctx.id)
        .await
        .map_err(|e| ApiError::Internal(e.message))?;
    if blocked {
        return Err(ApiError::http(
            409,
            format!("Session {} is blocked; apply is not allowed.", ctx.id),
        ));
    }
    tokio::spawn(run_round(state.clone(), ctx.clone(), Round::Apply, String::new()));
    Ok(accepted(&ctx))
}

pub async fn import(State(state): State<AppState>, headers: HeaderMap, body: Bytes) -> ApiResult<Response> {
    let body = parse_body(&headers, &body)?;
    let user = current_user(&state, &headers).await?;
    require_operation_role(&user, OperationRole::Developer)?;
    let parsed = parse_iac(&body, IacKind::Import)?;
    let ctx = resolve_or_raise(&state, &parsed.request, &user, Some(OperationType::Import)).await?;
    tokio::spawn(run_round(
        state.clone(),
        ctx.clone(),
        Round::Import {
            is_partial: parsed.is_partial,
        },
        parsed.request.q().to_string(),
    ));
    Ok(accepted(&ctx))
}

#[allow(dead_code)]
fn unused(_: AppError) {}
