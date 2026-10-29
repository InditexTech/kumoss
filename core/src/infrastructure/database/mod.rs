// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Postgres connection pool and schema bootstrap.

use std::time::Duration;

use sqlx::error::ErrorKind as SqlErrorKind;
use sqlx::postgres::{PgPool, PgPoolOptions};

use crate::shared::error::{AppError, AppResult, ErrorKind};

const SCHEMA: &str = include_str!("schema.sql");

/// Serializes schema bootstrap across replicas booting at the same time.
const SCHEMA_LOCK_KEY: i64 = 0x4B55_4D4F_5353; // "KUMOSS"

/// Translate a driver error the way the Python session manager did:
/// integrity violations surface as-is (a bug, not a modelled failure),
/// everything else as a 500 "Session error".
pub fn db_error(e: sqlx::Error) -> AppError {
    if let Some(db) = e.as_database_error() {
        match db.kind() {
            SqlErrorKind::UniqueViolation
            | SqlErrorKind::ForeignKeyViolation
            | SqlErrorKind::NotNullViolation
            | SqlErrorKind::CheckViolation => {
                return AppError::kind(ErrorKind::Internal, format!("(IntegrityError) {}", db.message()), 500);
            }
            _ => {}
        }
    }
    tracing::error!("Session error: {e}");
    AppError::new(format!("Session error {e}"), 500)
}

/// Whether `e` is a unique-constraint violation.
pub fn is_unique_violation(e: &sqlx::Error) -> bool {
    e.as_database_error()
        .is_some_and(|d| matches!(d.kind(), SqlErrorKind::UniqueViolation))
}

/// Connect, verify with `SELECT 1`, and create any missing schema object.
pub async fn initialize(url: &str) -> AppResult<PgPool> {
    let fail = |e: String| {
        tracing::error!("Failed to initialize session manager: {e}");
        AppError::new(format!("Failed to initialize database: {e}"), 500)
    };
    if url.is_empty() {
        return Err(fail(
            "KUMOSS_SQL_DATABASE_URL environment variable is not set. Please set it to connect to PostgreSQL.".into(),
        ));
    }
    let pool = PgPoolOptions::new()
        .max_connections(10)
        .min_connections(0)
        .acquire_timeout(Duration::from_secs(30))
        .test_before_acquire(true)
        .connect(url)
        .await
        .map_err(|e| fail(e.to_string()))?;
    sqlx::query("SELECT 1")
        .execute(&pool)
        .await
        .map_err(|e| fail(e.to_string()))?;
    tracing::info!("Session manager initialized successfully");

    let mut tx = pool.begin().await.map_err(|e| fail(e.to_string()))?;
    let created: AppResult<()> = async {
        sqlx::query("SELECT pg_advisory_xact_lock($1)")
            .bind(SCHEMA_LOCK_KEY)
            .execute(&mut *tx)
            .await
            .map_err(db_error)?;
        sqlx::raw_sql(SCHEMA).execute(&mut *tx).await.map_err(db_error)?;
        Ok(())
    }
    .await;
    match created {
        Ok(()) => {
            tx.commit().await.map_err(|e| fail(e.to_string()))?;
            tracing::info!("Database tables created/verified successfully");
        }
        Err(e) => {
            tracing::error!("Error creating database tables: {}", e.message);
            return Err(e);
        }
    }
    tracing::info!("Database client initialized");
    Ok(pool)
}
