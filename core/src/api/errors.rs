// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! The error responses of the HTTP API, shaped like FastAPI's: an
//! `HTTPException` is `{"detail": ...}`, a request validation failure is a
//! 422 with pydantic's error list, and anything unexpected is a plain-text
//! 500.

use axum::http::{HeaderMap, HeaderName, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use serde_json::{Value, json};

use crate::shared::error::{AppError, ErrorKind};

#[derive(Debug)]
pub enum ApiError {
    Http {
        status: u16,
        detail: Value,
        headers: Vec<(&'static str, String)>,
    },
    Validation(Vec<Value>),
    Internal(String),
}

impl ApiError {
    pub fn http(status: u16, detail: impl Into<String>) -> Self {
        ApiError::Http {
            status,
            detail: Value::String(detail.into()),
            headers: Vec::new(),
        }
    }

    pub fn with_header(mut self, name: &'static str, value: impl Into<String>) -> Self {
        if let ApiError::Http { headers, .. } = &mut self {
            headers.push((name, value.into()));
        }
        self
    }
}

/// `except ExceptionHandler as e: raise HTTPException(e.error_code, e.message)`;
/// errors that were not `ExceptionHandler`s in the Python core surface as
/// an unhandled 500.
impl From<AppError> for ApiError {
    fn from(e: AppError) -> Self {
        if e.kind == ErrorKind::Internal {
            tracing::error!("Unhandled error: {}", e.message);
            return ApiError::Internal(e.message);
        }
        ApiError::http(e.code, e.message)
    }
}

pub fn json_response(status: StatusCode, body: &Value) -> Response {
    let bytes = serde_json::to_vec(body).unwrap_or_default();
    (status, [(axum::http::header::CONTENT_TYPE, "application/json")], bytes).into_response()
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        match self {
            ApiError::Http {
                status,
                detail,
                headers,
            } => {
                let code = StatusCode::from_u16(status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
                let mut resp = json_response(code, &json!({"detail": detail}));
                let map: &mut HeaderMap = resp.headers_mut();
                for (k, v) in headers {
                    if let (Ok(name), Ok(value)) = (HeaderName::try_from(k), HeaderValue::try_from(v)) {
                        map.insert(name, value);
                    }
                }
                resp
            }
            ApiError::Validation(errors) => json_response(StatusCode::UNPROCESSABLE_ENTITY, &json!({"detail": errors})),
            ApiError::Internal(_) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                [(axum::http::header::CONTENT_TYPE, "text/plain; charset=utf-8")],
                "Internal Server Error",
            )
                .into_response(),
        }
    }
}

pub type ApiResult<T> = Result<T, ApiError>;
