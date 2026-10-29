// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Request authentication: OIDC bearer-token validation.

pub mod oidc;

pub use oidc::{Clock, OidcTokenValidator, SystemClock, build_validator};
