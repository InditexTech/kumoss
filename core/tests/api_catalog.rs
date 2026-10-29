// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Replays the request-validation catalog captured from the FastAPI core
//! (`testdata/fastapi_validation_errors.json`) through the real router and
//! asserts identical status codes and bodies, plus the routing fallbacks
//! and the published OpenAPI document. Needs a Postgres
//! (`KUMOSS_TEST_DATABASE_URL`): with OIDC disabled every request resolves
//! the local developer, as the FastAPI capture's dependency override did.

use std::sync::Arc;

use async_trait::async_trait;
use axum::body::Body;
use axum::http::{Request, StatusCode};
use http_body_util::BodyExt;
use kumoss_core::application::state::AppState;
use kumoss_core::domain::ports::{ObjectMetadata, ObjectStorage};
use kumoss_core::domain::services::database::DatabaseService;
use kumoss_core::domain::services::user::UserService;
use kumoss_core::infrastructure::external::notifications::NotificationServiceClient;
use kumoss_core::infrastructure::filesystem::workspace::WorkspaceService;
use kumoss_core::infrastructure::llm::sidecar::SidecarClient;
use kumoss_core::infrastructure::redis::RedisCache;
use kumoss_core::infrastructure::templates::fetcher::PromptFetcher;
use kumoss_core::shared::config::SystemConfig;
use kumoss_core::shared::error::AppResult;
use serde_json::{Value, json};
use tower::ServiceExt;

struct NoStorage;

#[async_trait]
impl ObjectStorage for NoStorage {
    async fn ensure_bucket(&self) -> AppResult<()> {
        Ok(())
    }
    async fn put(&self, _: &str, _: Vec<u8>, _: &str, _: &ObjectMetadata) -> AppResult<()> {
        Ok(())
    }
    fn metadata_header_prefix(&self) -> &'static str {
        "x-amz-meta-"
    }
    async fn get(&self, _: &str) -> AppResult<Vec<u8>> {
        Ok(Vec::new())
    }
    async fn exists(&self, _: &str) -> AppResult<bool> {
        Ok(false)
    }
    async fn delete(&self, _: &str) -> AppResult<()> {
        Ok(())
    }
    async fn presigned_get_url(&self, key: &str, _: Option<u64>) -> AppResult<String> {
        Ok(format!("http://storage/{key}"))
    }
}

async fn state(url: &str) -> AppState {
    // SAFETY: set once, before any thread reads them.
    unsafe {
        std::env::set_var("KUMOSS_CATALOG_DB", url);
        std::env::set_var("KUMOSS_CATALOG_IAC", "t");
        std::env::set_var("KUMOSS_CATALOG_LLM", "t");
    }
    let cfg = SystemConfig::from_value(&json!({
        "database": {"kumoss_database_url_env": "KUMOSS_CATALOG_DB"},
        "services": {"iac": {"token_env": "KUMOSS_CATALOG_IAC"}, "llm": {"token_env": "KUMOSS_CATALOG_LLM"}},
    }))
    .expect("config");
    let cfg: &'static SystemConfig = Box::leak(Box::new(cfg));
    let pool = kumoss_core::infrastructure::database::initialize(url)
        .await
        .expect("database");
    let storage: Arc<dyn ObjectStorage> = Arc::new(NoStorage);
    let db = DatabaseService::new(pool, RedisCache::disabled(), storage.clone(), cfg);
    let users = UserService::new(db.clone(), cfg);
    AppState {
        cfg,
        db,
        users: users.clone(),
        notifications: NotificationServiceClient::new(cfg, users),
        storage,
        sidecar: SidecarClient::new(cfg),
        fetcher: PromptFetcher::new(&cfg.telemetry.collector_url),
        workspace: WorkspaceService::new(cfg),
        oidc: None,
    }
}

async fn send(
    app: &axum::Router,
    method: &str,
    path: &str,
    body: Option<&Value>,
) -> (StatusCode, String, Vec<(String, String)>) {
    let mut req = Request::builder().method(method).uri(path);
    let body = match body {
        Some(b) => {
            req = req.header("content-type", "application/json");
            Body::from(serde_json::to_vec(b).unwrap())
        }
        None => Body::empty(),
    };
    let resp = app.clone().oneshot(req.body(body).unwrap()).await.unwrap();
    let status = resp.status();
    let headers = resp
        .headers()
        .iter()
        .map(|(k, v)| (k.to_string(), v.to_str().unwrap_or("").to_string()))
        .collect();
    let bytes = resp.into_body().collect().await.unwrap().to_bytes();
    (status, String::from_utf8_lossy(&bytes).into_owned(), headers)
}

#[tokio::test]
async fn replays_fastapi_catalog() {
    let Ok(url) = std::env::var("KUMOSS_TEST_DATABASE_URL") else {
        eprintln!("KUMOSS_TEST_DATABASE_URL unset; skipping");
        return;
    };
    let app = kumoss_core::api::router(state(&url).await);
    let catalog: Vec<Value> = serde_json::from_str(include_str!("../testdata/fastapi_validation_errors.json")).unwrap();
    let mut failures = Vec::new();
    for case in &catalog {
        let method = case["method"].as_str().unwrap();
        let path = case["path"].as_str().unwrap();
        let body = if case["body"].is_null() {
            None
        } else {
            Some(&case["body"])
        };
        for prefix in ["", "/api"] {
            let (status, text, _) = send(&app, method, &format!("{prefix}{path}"), body).await;
            let expected_status = case["status"].as_u64().unwrap() as u16;
            let expected: Value = serde_json::from_str(case["response"].as_str().unwrap()).unwrap();
            let got: Value = serde_json::from_str(&text).unwrap_or(Value::String(text.clone()));
            if status.as_u16() != expected_status || got != expected {
                failures.push(format!(
                    "{method} {prefix}{path} {}\n  got {status} {got}\n  want {expected_status} {expected}",
                    case["body"]
                ));
            }
        }
    }
    assert!(
        failures.is_empty(),
        "{} mismatches:\n{}",
        failures.len(),
        failures.join("\n")
    );

    // Routing fallbacks, as FastAPI answered them.
    let (status, text, _) = send(&app, "GET", "/nonexistent", None).await;
    assert_eq!(
        (status, text.as_str()),
        (StatusCode::NOT_FOUND, r#"{"detail":"Not Found"}"#)
    );
    let (status, text, headers) = send(&app, "DELETE", "/v1/users/me", None).await;
    assert_eq!(
        (status, text.as_str()),
        (StatusCode::METHOD_NOT_ALLOWED, r#"{"detail":"Method Not Allowed"}"#)
    );
    assert!(
        headers.iter().any(|(k, v)| k == "allow" && v.contains("GET")),
        "{headers:?}"
    );

    // The published OpenAPI document is FastAPI's.
    let (status, text, _) = send(&app, "GET", "/api/openapi.json", None).await;
    assert_eq!(status, StatusCode::OK);
    let served: Value = serde_json::from_str(&text).unwrap();
    let snapshot: Value = serde_json::from_str(include_str!("../resources/openapi.json")).unwrap();
    assert_eq!(served["paths"], snapshot["paths"]);

    // users/me resolves the local developer with the top roles.
    let (status, text, _) = send(&app, "GET", "/api/v1/users/me", None).await;
    assert_eq!(status, StatusCode::OK);
    let me: Value = serde_json::from_str(&text).unwrap();
    assert_eq!(me["email"], "dev@kumoss.local");
    assert_eq!(me["operation_role"], "devops");
    assert_eq!(me["panel_role"], "admin");

    // Auth config is public and reports the artifact metadata prefix.
    let (_, text, _) = send(&app, "GET", "/api/v1/auth/config", None).await;
    assert_eq!(
        serde_json::from_str::<Value>(&text).unwrap(),
        json!({"issuer_url": "", "client_id": "", "audience": "", "scope": "openid profile email", "artifact_metadata_header_prefix": "x-amz-meta-"})
    );
}
