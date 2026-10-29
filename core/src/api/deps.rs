// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Authentication and role-based authorization of API requests.

use axum::http::HeaderMap;
use uuid::Uuid;

use crate::api::errors::{ApiError, ApiResult};
use crate::application::state::AppState;
use crate::domain::entities::User;
use crate::shared::constants::{OperationRole, PanelRole};

/// `HTTPBearer(auto_error=False)`: the credentials of an `Authorization:
/// Bearer <token>` header, or `None`.
fn bearer(headers: &HeaderMap) -> Option<String> {
    let value = headers.get("authorization")?.to_str().ok()?;
    let (scheme, credentials) = match value.split_once(' ') {
        Some((s, c)) => (s, c),
        None => (value, ""),
    };
    if value.is_empty() || scheme.is_empty() || credentials.is_empty() {
        return None;
    }
    if !scheme.eq_ignore_ascii_case("bearer") {
        return None;
    }
    Some(credentials.to_string())
}

/// The authenticated caller. With OIDC disabled every request runs as the
/// local developer identity.
pub async fn current_user(state: &AppState, headers: &HeaderMap) -> ApiResult<User> {
    if state.cfg.oidc.issuer_url.is_empty() {
        return state
            .users
            .resolve(None)
            .await
            .map_err(|e| ApiError::Internal(e.message));
    }
    let (Some(token), Some(validator)) = (bearer(headers), state.oidc.as_ref()) else {
        return Err(ApiError::http(401, "Not authenticated").with_header("www-authenticate", "Bearer"));
    };
    let claims = validator.validate(&token).await.map_err(|e| {
        ApiError::http(401, e.message).with_header("www-authenticate", "Bearer error=\"invalid_token\"")
    })?;
    state
        .users
        .resolve(Some(&claims))
        .await
        .map_err(|e| ApiError::Internal(e.message))
}

pub fn require_operation_role(user: &User, minimum: OperationRole) -> ApiResult<()> {
    if !user.operation_role.at_least(minimum) {
        return Err(ApiError::http(
            403,
            format!("Requires operation role '{}' or higher", minimum.value()),
        ));
    }
    Ok(())
}

pub fn require_panel_role(user: &User, minimum: PanelRole) -> ApiResult<()> {
    match user.panel_role {
        Some(role) if role.at_least(minimum) => Ok(()),
        _ => Err(ApiError::http(
            403,
            format!("Requires admin-panel role '{}' or higher", minimum.value()),
        )),
    }
}

/// The owner may always access; non-owners may read with panel viewer+.
pub async fn assert_session_access(state: &AppState, user: &User, session_id: &Uuid, write: bool) -> ApiResult<()> {
    let owner = state.db.get_session_owner(session_id).await.map_err(ApiError::from)?;
    if owner == user.id {
        return Ok(());
    }
    if !write && user.panel_role.is_some() {
        return Ok(());
    }
    Err(ApiError::http(403, "Not the session owner"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bearer_parsing() {
        let mut h = HeaderMap::new();
        assert_eq!(bearer(&h), None);
        h.insert("authorization", "Bearer abc".parse().unwrap());
        assert_eq!(bearer(&h).as_deref(), Some("abc"));
        h.insert("authorization", "bearer  abc".parse().unwrap());
        assert_eq!(bearer(&h).as_deref(), Some(" abc"));
        h.insert("authorization", "Basic abc".parse().unwrap());
        assert_eq!(bearer(&h), None);
        h.insert("authorization", "Bearer".parse().unwrap());
        assert_eq!(bearer(&h), None);
    }
}
