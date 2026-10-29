// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Server-sent events for session progress.
//!
//! The stream polls the session's latest status every 5 seconds and closes
//! on a terminal status (COMPLETED, UNCOMPLETED or FAILED) or after
//! `orchestration.max_session_events_iteration` polls (the session itself
//! is preserved). Messages lose their double quotes on the way out.

use std::time::Duration;

use axum::body::Body;
use axum::extract::{Path, State};
use axum::http::{HeaderMap, HeaderValue, StatusCode, header};
use axum::response::Response;
use serde_json::json;

use crate::api::deps::{assert_session_access, current_user};
use crate::api::errors::ApiResult;
use crate::api::validation::{Errors, path_uuid};
use crate::application::state::AppState;
use crate::shared::constants::SessionStatus;
use crate::shared::pyfmt;

pub async fn subscribe(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(session_id): Path<String>,
) -> ApiResult<Response> {
    let user = current_user(&state, &headers).await?;
    let mut errs = Errors::default();
    let sid = path_uuid(&mut errs, "session_id", &session_id);
    errs.finish()?;
    let sid = sid.expect("validated");
    assert_session_access(&state, &user, &sid, false).await?;
    tokio::time::sleep(Duration::from_secs(2)).await;
    state.db.get_session_summary(&sid).await?;

    let max = state.cfg.orchestration.max_session_events_iteration;
    let db = state.db.clone();
    let stream = async_stream::stream! {
        yield Ok::<_, std::convert::Infallible>(": keepalive\n\n".to_string());
        for _ in 0..max.max(0) {
            let status = match db.get_last_status(&sid).await {
                Ok(s) => s,
                Err(e) => {
                    tracing::error!("{}", e.message);
                    tokio::time::sleep(Duration::from_secs(4)).await;
                    continue;
                }
            };
            let payload = json!({
                "status_msg": status.status.name(),
                "detail": {"message": status.msg.replace('"', "")},
            });
            yield Ok(format!("data: {}\n\n", pyfmt::json_dumps(&payload)));
            if status.status == SessionStatus::Failed {
                tracing::error!("SSE session failed, closing stream. session_id={sid}");
                return;
            }
            if status.status == SessionStatus::Completed || status.status == SessionStatus::Uncompleted {
                tracing::info!("SSE session {}, closing stream. session_id={sid}", status.status.value());
                return;
            }
            tokio::time::sleep(Duration::from_secs(5)).await;
        }
    };
    let mut resp = Response::new(Body::from_stream(stream));
    *resp.status_mut() = StatusCode::OK;
    let h = resp.headers_mut();
    h.insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("text/event-stream; charset=utf-8"),
    );
    h.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-cache"));
    h.insert(header::CONNECTION, HeaderValue::from_static("keep-alive"));
    h.insert("x-accel-buffering", HeaderValue::from_static("no"));
    Ok(resp)
}
