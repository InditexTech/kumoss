// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Bootstraps the schema against a real Postgres (`KUMOSS_TEST_DATABASE_URL`),
//! twice, to prove the DDL is idempotent. Skipped when the variable is unset.

#[tokio::test]
async fn schema_bootstrap_is_idempotent() {
    let Ok(url) = std::env::var("KUMOSS_TEST_DATABASE_URL") else {
        eprintln!("KUMOSS_TEST_DATABASE_URL unset; skipping");
        return;
    };
    let pool = kumoss_core::infrastructure::database::initialize(&url)
        .await
        .expect("first bootstrap");
    pool.close().await;
    let pool = kumoss_core::infrastructure::database::initialize(&url)
        .await
        .expect("second bootstrap");
    pool.close().await;
}
