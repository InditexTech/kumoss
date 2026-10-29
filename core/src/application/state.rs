// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Process-wide dependencies, built once at boot.

use std::sync::Arc;

use crate::domain::ports::ObjectStorage;
use crate::domain::services::database::DatabaseService;
use crate::domain::services::user::UserService;
use crate::infrastructure::auth::oidc::OidcTokenValidator;
use crate::infrastructure::external::notifications::NotificationServiceClient;
use crate::infrastructure::filesystem::workspace::WorkspaceService;
use crate::infrastructure::llm::sidecar::SidecarClient;
use crate::infrastructure::templates::fetcher::PromptFetcher;
use crate::shared::config::SystemConfig;

#[derive(Clone)]
pub struct AppState {
    pub cfg: &'static SystemConfig,
    pub db: DatabaseService,
    pub users: UserService,
    pub notifications: NotificationServiceClient,
    pub storage: Arc<dyn ObjectStorage>,
    pub sidecar: SidecarClient,
    pub fetcher: PromptFetcher,
    pub workspace: WorkspaceService,
    pub oidc: Option<Arc<OidcTokenValidator>>,
}
