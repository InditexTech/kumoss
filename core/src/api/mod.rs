// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! The browser-facing HTTP API.
//!
//! Routes are served under the `/api` root path (what the proxy forwards)
//! and bare, as Starlette did with `root_path="/api"`. The OpenAPI document
//! is the published contract; the interactive docs load it from
//! `/api/openapi.json`.

pub mod deps;
pub mod errors;
pub mod requests;
pub mod v1;
pub mod validation;

use std::sync::LazyLock;
use std::time::Instant;

use axum::Router;
use axum::extract::{ConnectInfo, DefaultBodyLimit, Request};
use axum::http::{HeaderValue, Method, StatusCode, header};
use axum::middleware::{self, Next};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, patch, post, put};
use serde_json::{Value, json};
use tower_http::cors::{AllowHeaders, AllowMethods, AllowOrigin, CorsLayer};

use crate::api::errors::json_response;
use crate::application::state::AppState;

static OPENAPI: LazyLock<Vec<u8>> = LazyLock::new(|| {
    let mut spec: Value = serde_json::from_str(include_str!("../../resources/openapi.json")).expect("openapi snapshot");
    let version = std::env::var("APP_VERSION").unwrap_or_else(|_| env!("CARGO_PKG_VERSION").to_string());
    spec["info"]["version"] = Value::String(version);
    serde_json::to_vec(&spec).expect("openapi serializes")
});

fn html(body: &'static str) -> Response {
    ([(header::CONTENT_TYPE, "text/html; charset=utf-8")], body).into_response()
}

async fn openapi() -> Response {
    ([(header::CONTENT_TYPE, "application/json")], OPENAPI.as_slice()).into_response()
}

async fn swagger() -> Response {
    html(include_str!("../../resources/swagger.html"))
}

async fn swagger_redirect() -> Response {
    html(include_str!("../../resources/oauth2-redirect.html"))
}

async fn redoc() -> Response {
    html(include_str!("../../resources/redoc.html"))
}

async fn not_found() -> Response {
    json_response(StatusCode::NOT_FOUND, &json!({"detail": "Not Found"}))
}

async fn method_not_allowed() -> Response {
    json_response(StatusCode::METHOD_NOT_ALLOWED, &json!({"detail": "Method Not Allowed"}))
}

fn routes() -> Router<AppState> {
    use v1::{events, misc, repository, sessions, terraform};
    Router::new()
        .route("/openapi.json", get(openapi))
        .route("/docs", get(swagger))
        .route("/docs/oauth2-redirect", get(swagger_redirect))
        .route("/redoc", get(redoc))
        .route("/v1/iac/generate", post(terraform::generate))
        .route("/v1/iac/drift", post(terraform::drift))
        .route("/v1/iac/apply", post(terraform::apply))
        .route("/v1/iac/import", post(terraform::import))
        .route("/v1/events/subscribe/{session_id}", get(events::subscribe))
        .route("/v1/repository/pr/merge", put(repository::complete_pr))
        .route("/v1/repository/pr", put(repository::create_pr))
        .route("/v1/repository/parse", post(repository::parse_repository))
        .route("/v1/auth/config", get(misc::auth_config))
        .route("/v1/auth/authorize", post(misc::authorize))
        .route("/v1/admin/sessions/list", get(sessions::admin_sessions_list))
        .route("/v1/admin/sessions", get(sessions::admin_session_detail))
        .route(
            "/v1/admin/sessions/{session_id}/toggle_lock",
            patch(sessions::toggle_lock),
        )
        .route("/v1/admin/users", get(sessions::admin_users_list))
        .route("/v1/admin/users/{user_id}/roles", put(sessions::set_user_roles))
        .route("/v1/sessions/list", get(sessions::sessions_list))
        .route("/v1/sessions", get(sessions::session_detail))
        .route("/v1/mapping/resolve", post(misc::mapping_resolve))
        .route("/v1/users/me", get(sessions::users_me))
        .route("/v1/notifications", post(misc::submit_notification))
        .method_not_allowed_fallback(method_not_allowed)
}

/// uvicorn-style access log line.
async fn access_log(req: Request, next: Next) -> Response {
    let method = req.method().clone();
    let path = req
        .uri()
        .path_and_query()
        .map(|p| p.as_str().to_string())
        .unwrap_or_default();
    let version = req.version();
    let client = req
        .extensions()
        .get::<ConnectInfo<std::net::SocketAddr>>()
        .map(|c| c.0.to_string())
        .unwrap_or_else(|| "-".into());
    let started = Instant::now();
    let resp = next.run(req).await;
    let status = resp.status();
    tracing::info!(
        target: "kumoss_core::access",
        "{client} - \"{method} {path} {version:?}\" {} {} ({} ms)",
        status.as_u16(),
        status.canonical_reason().unwrap_or(""),
        started.elapsed().as_millis()
    );
    resp
}

fn cors(origins: &[String]) -> CorsLayer {
    let allow_origin = if origins.iter().any(|o| o == "*") {
        AllowOrigin::mirror_request()
    } else {
        AllowOrigin::list(origins.iter().filter_map(|o| HeaderValue::from_str(o).ok()))
    };
    CorsLayer::new()
        .allow_origin(allow_origin)
        .allow_credentials(true)
        .allow_methods(AllowMethods::list([
            Method::DELETE,
            Method::GET,
            Method::HEAD,
            Method::OPTIONS,
            Method::PATCH,
            Method::POST,
            Method::PUT,
        ]))
        .allow_headers(AllowHeaders::mirror_request())
        .max_age(std::time::Duration::from_secs(600))
}

pub fn router(state: AppState) -> Router {
    let api = routes();
    Router::new()
        .nest("/api", api.clone())
        .merge(api)
        .fallback(not_found)
        .layer(DefaultBodyLimit::disable())
        .layer(cors(&state.cfg.http.cors_origins))
        .layer(middleware::from_fn(access_log))
        .with_state(state)
}
