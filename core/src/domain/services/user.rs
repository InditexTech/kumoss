// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Internal user resolution, provisioning, and role management.

use crate::domain::entities::User;
use crate::domain::services::database::{DatabaseService, UserUpdate};
use crate::domain::value_objects::TokenClaims;
use crate::shared::config::SystemConfig;
use crate::shared::constants::{OperationRole, PanelRole};
use crate::shared::error::{AppResult, ErrorKind};

/// Identity used for every request while OIDC auth is disabled (blank
/// issuer_url). Resolved into a real users row so session FKs and the admin
/// panel work in local dev; always elevated to the top roles.
pub fn dev_claims() -> TokenClaims {
    TokenClaims {
        issuer: "urn:kumoss:dev".into(),
        subject: "dev".into(),
        email: Some("dev@kumoss.local".into()),
        name: Some("Local Developer".into()),
        email_verified: true,
    }
}

/// Identity resolution and role rules over the users store.
#[derive(Clone)]
pub struct UserService {
    db: DatabaseService,
    cfg: &'static SystemConfig,
}

impl UserService {
    pub fn new(db: DatabaseService, cfg: &'static SystemConfig) -> Self {
        Self { db, cfg }
    }

    /// Resolve token claims into the internal user, creating it on first
    /// login and syncing profile/elevation on every call.
    pub async fn resolve(&self, claims: Option<&TokenClaims>) -> AppResult<User> {
        let dev = dev_claims();
        let claims = claims.unwrap_or(&dev);
        let user = match self.db.get_user_by_identity(&claims.issuer, &claims.subject).await? {
            Some(u) => u,
            None => self.provision(claims).await?,
        };
        self.sync_profile(user, claims).await
    }

    fn is_elevated(&self, claims: &TokenClaims) -> bool {
        if claims.issuer == dev_claims().issuer {
            return true;
        }
        let Some(email) = &claims.email else {
            return false;
        };
        if !claims.email_verified {
            return false;
        }
        let root = crate::shared::pyfmt::strip(&self.cfg.admin.default_root_email).to_lowercase();
        !root.is_empty() && email.to_lowercase() == root
    }

    async fn provision(&self, claims: &TokenClaims) -> AppResult<User> {
        let elevated = self.is_elevated(claims);
        let created = self
            .db
            .create_user(
                &claims.issuer,
                &claims.subject,
                claims.email.as_deref(),
                claims.name.as_deref(),
                if elevated {
                    OperationRole::Devops
                } else {
                    OperationRole::Developer
                },
                if elevated { Some(PanelRole::Admin) } else { None },
            )
            .await;
        match created {
            Ok(u) => Ok(u),
            Err(e) if e.is(ErrorKind::UserAlreadyExists) => {
                match self.db.get_user_by_identity(&claims.issuer, &claims.subject).await? {
                    Some(u) => Ok(u),
                    None => Err(e),
                }
            }
            Err(e) => Err(e),
        }
    }

    async fn sync_profile(&self, user: User, claims: &TokenClaims) -> AppResult<User> {
        let mut values = UserUpdate::default();
        if let Some(email) = &claims.email
            && Some(email) != user.email.as_ref()
        {
            values.email = Some(email.clone());
        }
        if let Some(name) = &claims.name
            && Some(name) != user.display_name.as_ref()
        {
            values.display_name = Some(name.clone());
        }
        if self.is_elevated(claims) {
            // Elevation is one-way: never demote an already-higher role.
            if user.operation_role != OperationRole::Devops {
                values.operation_role = Some(OperationRole::Devops);
            }
            if user.panel_role != Some(PanelRole::Admin) {
                values.panel_role = Some(Some(PanelRole::Admin));
            }
        }
        if values.is_empty() {
            return Ok(user);
        }
        self.db.update_user(user.id, &values).await
    }

    pub async fn list_users(&self, offset: i64, limit: i64, search: Option<&str>) -> AppResult<(Vec<User>, i64)> {
        self.db.list_users(offset, limit, search).await
    }

    /// Emails of users holding `minimum` or a higher panel role.
    pub async fn emails_with_panel_role(&self, minimum: PanelRole) -> AppResult<Vec<String>> {
        self.db.list_emails_with_panel_role(minimum).await
    }

    pub async fn set_roles(
        &self,
        user_id: i64,
        operation_role: OperationRole,
        panel_role: Option<PanelRole>,
    ) -> AppResult<User> {
        self.db
            .update_user(
                user_id,
                &UserUpdate {
                    operation_role: Some(operation_role),
                    panel_role: Some(panel_role),
                    ..Default::default()
                },
            )
            .await
    }
}
