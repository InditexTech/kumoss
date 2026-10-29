// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Kumoss core entrypoint: load the configuration, bring up the database,
//! cache, object storage, prompt registry and git setup, then serve the API
//! on 0.0.0.0:8000 until SIGINT/SIGTERM.

use std::net::SocketAddr;
use std::process::ExitCode;

use kumoss_core::api;
use kumoss_core::application::state::AppState;
use kumoss_core::domain::services::database::DatabaseService;
use kumoss_core::domain::services::user::UserService;
use kumoss_core::infrastructure::auth::oidc::build_validator;
use kumoss_core::infrastructure::database;
use kumoss_core::infrastructure::external::notifications::NotificationServiceClient;
use kumoss_core::infrastructure::filesystem::credentials::configure_git_credentials;
use kumoss_core::infrastructure::filesystem::workspace::WorkspaceService;
use kumoss_core::infrastructure::llm::sidecar::SidecarClient;
use kumoss_core::infrastructure::redis::RedisCache;
use kumoss_core::infrastructure::storage::{default_object_storage, terraform_state_storage};
use kumoss_core::infrastructure::telemetry;
use kumoss_core::infrastructure::templates::fetcher::PromptFetcher;
use kumoss_core::infrastructure::templates::seeder::{PromptSeeder, default_seed_dir};
use kumoss_core::shared::config::{self, SystemConfig};
use kumoss_core::shared::logger;

fn main() -> ExitCode {
    logger::init();
    let cfg = match SystemConfig::load() {
        Ok(c) => config::install(c),
        Err(e) => {
            tracing::error!("Invalid system configuration: {e}");
            return ExitCode::FAILURE;
        }
    };
    // The OTLP exporter's blocking client must be built outside the runtime.
    telemetry::init_providers(cfg);
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .expect("tokio runtime");
    let code = runtime.block_on(serve(cfg));
    telemetry::shutdown_providers();
    tracing::info!("Tracer providers flushed and shut down");
    code
}

async fn serve(cfg: &'static SystemConfig) -> ExitCode {
    tracing::info!("Starting Kumoss application...");
    let pool = match database::initialize(&cfg.database.kumoss_database_url()).await {
        Ok(p) => {
            tracing::info!("Database initialized successfully");
            p
        }
        Err(e) => {
            tracing::error!("Failed to initialize database: {}", e.message);
            return ExitCode::FAILURE;
        }
    };
    let cache = match RedisCache::initialize(&cfg.redis).await {
        Ok(c) => {
            tracing::info!("Redis initialized successfully");
            c
        }
        Err(e) => {
            tracing::error!("Failed to initialize redis: {}", e.message);
            return ExitCode::FAILURE;
        }
    };
    let storage = match async {
        let storage = default_object_storage().await?;
        storage.ensure_bucket().await?;
        if let Some(state_storage) = terraform_state_storage().await? {
            state_storage.ensure_bucket().await?;
        }
        Ok::<_, kumoss_core::shared::error::AppError>(storage)
    }
    .await
    {
        Ok(s) => {
            tracing::info!("Object storage initialized successfully");
            s
        }
        Err(e) => {
            tracing::error!("Failed to initialize object storage: {}", e.message);
            return ExitCode::FAILURE;
        }
    };
    if let Err(e) = PromptSeeder::new(default_seed_dir(), &cfg.telemetry.collector_url)
        .ensure_seeded()
        .await
    {
        tracing::error!("Failed to seed prompts into Phoenix: {}", e.message);
        return ExitCode::FAILURE;
    }
    if let Err(e) = configure_git_credentials(cfg, None).await {
        tracing::warn!("Failed to configure git credentials: {}", e.message);
    }

    let db = DatabaseService::new(pool.clone(), cache, storage.clone(), cfg);
    let users = UserService::new(db.clone(), cfg);
    let state = AppState {
        cfg,
        db: db.clone(),
        users: users.clone(),
        notifications: NotificationServiceClient::new(cfg, users),
        storage,
        sidecar: SidecarClient::new(cfg),
        fetcher: PromptFetcher::new(&cfg.telemetry.collector_url),
        workspace: WorkspaceService::new(cfg),
        oidc: build_validator(&cfg.oidc),
    };

    let addr = SocketAddr::from(([0, 0, 0, 0], 8000));
    let listener = match tokio::net::TcpListener::bind(addr).await {
        Ok(l) => l,
        Err(e) => {
            tracing::error!("Cannot bind {addr}: {e}");
            return ExitCode::FAILURE;
        }
    };
    tracing::info!("Kumoss core listening on http://{addr}");
    let app = api::router(state).into_make_service_with_connect_info::<SocketAddr>();
    if let Err(e) = axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await
    {
        tracing::error!("Server error: {e}");
    }

    tracing::info!("Shutting down Kumoss application...");
    tracing::info!("Redis connection closed");
    pool.close().await;
    tracing::info!("Database connection closed");
    ExitCode::SUCCESS
}

async fn shutdown_signal() {
    let ctrl_c = async {
        let _ = tokio::signal::ctrl_c().await;
    };
    let terminate = async {
        if let Ok(mut s) = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
            s.recv().await;
        }
    };
    tokio::select! {
        _ = ctrl_c => {},
        _ = terminate => {},
    }
}
