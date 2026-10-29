// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Session read models, for the caller's own sessions and (admin) across
//! every user.

use axum::body::Bytes;
use axum::extract::{Path, RawQuery, State};
use axum::http::{HeaderMap, StatusCode};
use axum::response::Response;
use serde_json::json;

use crate::api::deps::{assert_session_access, current_user, require_panel_role};
use crate::api::errors::{ApiError, ApiResult, json_response};
use crate::api::validation::{EmbeddedBody, Errors, QueryParams, boolean, loc, parse_body, path_int, path_uuid};
use crate::application::state::AppState;
use crate::domain::entities::User;
use crate::domain::services::database::SessionFilter;
use crate::shared::constants::{OperationRole, OperationType, PanelRole, SessionStatus};

struct ListParams {
    page: i64,
    page_size: i64,
    filter: SessionFilter,
}

fn list_params(q: &QueryParams, errs: &mut Errors, with_user_email: bool) -> ListParams {
    let page = q.int(errs, "page", 1, Some(1), None);
    let page_size = q.int(errs, "page_size", 20, Some(1), Some(100));
    let operation = q.opt_enum(errs, "operation", OperationType::from_value, OperationType::expected());
    let status = q.opt_enum(errs, "status", SessionStatus::from_value, SessionStatus::expected());
    let search = q.opt_str(errs, "search", 200);
    let user_email = if with_user_email {
        q.opt_str(errs, "user_email", 254)
    } else {
        None
    };
    ListParams {
        page,
        page_size,
        filter: SessionFilter {
            user_pk: None,
            operation,
            status,
            search,
            user_email,
        },
    }
}

/// Paginated summaries of the caller's own sessions.
pub async fn sessions_list(
    State(state): State<AppState>,
    headers: HeaderMap,
    RawQuery(query): RawQuery,
) -> ApiResult<Response> {
    let user = current_user(&state, &headers).await?;
    let q = QueryParams::parse(query.as_deref());
    let mut errs = Errors::default();
    let mut p = list_params(&q, &mut errs, false);
    errs.finish()?;
    p.filter.user_pk = Some(user.id);
    let page = state
        .db
        .list_sessions(&p.filter, (p.page - 1) * p.page_size, p.page_size)
        .await?;
    Ok(json_response(
        StatusCode::OK,
        &serde_json::to_value(page).unwrap_or_default(),
    ))
}

/// The complete read model for the session detail view.
pub async fn session_detail(
    State(state): State<AppState>,
    headers: HeaderMap,
    RawQuery(query): RawQuery,
) -> ApiResult<Response> {
    let user = current_user(&state, &headers).await?;
    let q = QueryParams::parse(query.as_deref());
    let mut errs = Errors::default();
    let session_id = q.required_uuid(&mut errs, "id");
    let include_chat_history = q.bool(&mut errs, "include_chat_history", false);
    errs.finish()?;
    let session_id = session_id.expect("validated");
    assert_session_access(&state, &user, &session_id, false).await?;
    let detail = state
        .db
        .get_session_detail(&session_id, include_chat_history, false)
        .await?;
    Ok(json_response(
        StatusCode::OK,
        &serde_json::to_value(detail.user_view()).unwrap_or_default(),
    ))
}

async fn panel_user(state: &AppState, headers: &HeaderMap, minimum: PanelRole) -> ApiResult<User> {
    let user = current_user(state, headers).await?;
    require_panel_role(&user, PanelRole::Viewer)?;
    require_panel_role(&user, minimum)?;
    Ok(user)
}

/// Cross-user paginated session summaries for the admin panel.
pub async fn admin_sessions_list(
    State(state): State<AppState>,
    headers: HeaderMap,
    RawQuery(query): RawQuery,
) -> ApiResult<Response> {
    panel_user(&state, &headers, PanelRole::Viewer).await?;
    let q = QueryParams::parse(query.as_deref());
    let mut errs = Errors::default();
    let p = list_params(&q, &mut errs, true);
    errs.finish()?;
    let page = state
        .db
        .list_sessions(&p.filter, (p.page - 1) * p.page_size, p.page_size)
        .await?;
    Ok(json_response(
        StatusCode::OK,
        &serde_json::to_value(page).unwrap_or_default(),
    ))
}

/// Any session's aggregate, with both conversation records available.
pub async fn admin_session_detail(
    State(state): State<AppState>,
    headers: HeaderMap,
    RawQuery(query): RawQuery,
) -> ApiResult<Response> {
    panel_user(&state, &headers, PanelRole::Viewer).await?;
    let q = QueryParams::parse(query.as_deref());
    let mut errs = Errors::default();
    let session_id = q.required_uuid(&mut errs, "id");
    let include_chat_history = q.bool(&mut errs, "include_chat_history", false);
    let include_history = q.bool(&mut errs, "include_history", false);
    errs.finish()?;
    let detail = state
        .db
        .get_session_detail(&session_id.expect("validated"), include_chat_history, include_history)
        .await?;
    Ok(json_response(
        StatusCode::OK,
        &serde_json::to_value(detail).unwrap_or_default(),
    ))
}

/// Lock or unlock a session's plan from being applied.
pub async fn toggle_lock(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(session_id): Path<String>,
    body: Bytes,
) -> ApiResult<Response> {
    let body = parse_body(&headers, &body)?;
    panel_user(&state, &headers, PanelRole::Editor).await?;
    let mut errs = Errors::default();
    let sid = path_uuid(&mut errs, "session_id", &session_id);
    let embedded = EmbeddedBody::new(&body);
    let locked = embedded
        .field(&mut errs, "locked")
        .and_then(|v| boolean(&mut errs, &loc(&["body", "locked"]), v));
    errs.finish()?;
    let (sid, locked) = (sid.expect("validated"), locked.expect("validated"));
    let updated = state
        .db
        .set_lock(&sid, locked)
        .await
        .map_err(|e| ApiError::Internal(e.message))?;
    if !updated {
        return Err(ApiError::http(404, format!("Session {sid} not found.")));
    }
    Ok(json_response(
        StatusCode::OK,
        &json!({"uuid": sid, "is_blocked": locked}),
    ))
}

fn user_entry(user: &User) -> serde_json::Value {
    json!({
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "operation_role": user.operation_role,
        "panel_role": user.panel_role,
        "issuer": user.issuer,
        "subject": user.subject,
        "created_at": crate::shared::serde_util::format_datetime(&user.created_at),
    })
}

/// Internal users with their roles.
pub async fn admin_users_list(
    State(state): State<AppState>,
    headers: HeaderMap,
    RawQuery(query): RawQuery,
) -> ApiResult<Response> {
    panel_user(&state, &headers, PanelRole::Admin).await?;
    let q = QueryParams::parse(query.as_deref());
    let mut errs = Errors::default();
    let page = q.int(&mut errs, "page", 1, Some(1), None);
    let page_size = q.int(&mut errs, "page_size", 20, Some(1), Some(100));
    let search = q.opt_str(&mut errs, "search", 254);
    errs.finish()?;
    let (users, total) = state
        .users
        .list_users((page - 1) * page_size, page_size, search.as_deref())
        .await
        .map_err(|e| ApiError::Internal(e.message))?;
    Ok(json_response(
        StatusCode::OK,
        &json!({
            "items": users.iter().map(user_entry).collect::<Vec<_>>(),
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": if total > 0 { (total + page_size - 1) / page_size } else { 0 },
        }),
    ))
}

/// Set a user's roles (full-state assignment).
pub async fn set_user_roles(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(user_id): Path<String>,
    body: Bytes,
) -> ApiResult<Response> {
    let body = parse_body(&headers, &body)?;
    let caller = panel_user(&state, &headers, PanelRole::Admin).await?;
    let mut errs = Errors::default();
    let user_id = path_int(&mut errs, "user_id", &user_id);
    let mut operation_role = None;
    let mut panel_role = None;
    if let Some(obj) = crate::api::validation::model_body(&mut errs, &body) {
        match obj.get("operation_role") {
            None => errs.push(
                "missing",
                &loc(&["body", "operation_role"]),
                "Field required",
                serde_json::Value::Object(obj.clone()),
                None,
            ),
            Some(v) => {
                operation_role = crate::api::validation::enumeration(
                    &mut errs,
                    &loc(&["body", "operation_role"]),
                    v,
                    OperationRole::from_value,
                    OperationRole::expected(),
                )
            }
        }
        if let Some(v) = obj.get("panel_role").filter(|v| !v.is_null()) {
            panel_role = crate::api::validation::enumeration(
                &mut errs,
                &loc(&["body", "panel_role"]),
                v,
                PanelRole::from_value,
                PanelRole::expected(),
            );
        }
    }
    errs.finish()?;
    let user_id = user_id.expect("validated");
    if caller.id == user_id && panel_role != Some(PanelRole::Admin) {
        return Err(ApiError::http(409, "A panel admin cannot remove their own admin role."));
    }
    let user = state
        .users
        .set_roles(user_id, operation_role.expect("validated"), panel_role)
        .await?;
    Ok(json_response(StatusCode::OK, &user_entry(&user)))
}

/// The authenticated caller's identity and roles.
pub async fn users_me(State(state): State<AppState>, headers: HeaderMap) -> ApiResult<Response> {
    let user = current_user(&state, &headers).await?;
    Ok(json_response(
        StatusCode::OK,
        &json!({
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "operation_role": user.operation_role,
            "panel_role": user.panel_role,
        }),
    ))
}
