// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! The URI-driven, session-iterating IaC requests, once validated.

use uuid::Uuid;

use crate::shared::constants::TerraformProvider;

/// A first call: it creates the session.
#[derive(Debug, Clone, PartialEq)]
pub struct FirstCall {
    pub repo_uri: String,
    pub scope_id: String,
    pub terraform_provider: TerraformProvider,
    pub iac_path: Option<String>,
    pub q: String,
}

#[derive(Debug, Clone, PartialEq)]
pub enum IacRequest {
    First(FirstCall),
    /// An iteration call on an existing session.
    Iteration {
        session_id: Uuid,
        q: String,
    },
    /// A session-only request (apply).
    Session {
        session_id: Uuid,
    },
}

impl IacRequest {
    pub fn first_call(&self) -> Option<&FirstCall> {
        match self {
            IacRequest::First(f) => Some(f),
            _ => None,
        }
    }

    pub fn session_id(&self) -> Option<Uuid> {
        match self {
            IacRequest::First(_) => None,
            IacRequest::Iteration { session_id, .. } | IacRequest::Session { session_id } => Some(*session_id),
        }
    }

    pub fn repo_uri(&self) -> Option<&str> {
        self.first_call().map(|f| f.repo_uri.as_str())
    }

    pub fn q(&self) -> &str {
        match self {
            IacRequest::First(f) => &f.q,
            IacRequest::Iteration { q, .. } => q,
            IacRequest::Session { .. } => "",
        }
    }
}
