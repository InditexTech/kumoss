// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Validation of the IaC request bodies (`GenerateRequest`, `DriftRequest`,
//! `ImportRequest`, `ApplyRequest`), with the pydantic models' rules and
//! messages.

use serde_json::{Map, Value};
use uuid::Uuid;

use crate::api::errors::{ApiError, ApiResult};
use crate::api::validation::{self as v, Errors, loc};
use crate::application::iac_requests::{FirstCall, IacRequest};
use crate::shared::config::urlsplit;
use crate::shared::constants::TerraformProvider;
use crate::shared::pyfmt;
use crate::shared::urls::is_https_url;

/// Accept only https repository URIs that carry no secret in their
/// userinfo. A userinfo *username* is fine (Azure DevOps' clone URL has an
/// `<org>@` prefix); a password component, even empty, is a credential.
pub fn validate_repo_uri(repo_uri: &str) -> Result<String, &'static str> {
    let repo_uri = pyfmt::strip(repo_uri);
    if !is_https_url(repo_uri) {
        return Err(
            "repo_uri must be an https:// URL (e.g. `https://github.com/org/repo.git`); SSH, git://, http://, file:// and local paths are not supported.",
        );
    }
    if urlsplit(repo_uri).password.is_some() {
        return Err(
            "repo_uri must not embed a password or token; pass the repository URI without the `:<secret>` part (a bare `user@host` prefix is fine).",
        );
    }
    Ok(repo_uri.to_string())
}

/// A `RepoUri` field: a string, then the URI rules.
pub fn repo_uri_field(errs: &mut Errors, l: &[Value], raw: &Value) -> Option<String> {
    let s = v::string(errs, l, raw, None, None)?;
    match validate_repo_uri(&s) {
        Ok(u) => Some(u),
        Err(msg) => {
            errs.value_error(l, msg, raw.clone());
            None
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IacKind {
    Generate,
    Drift,
    Import,
}

/// A validated IaC request plus its `is_partial` flag.
pub struct ParsedIac {
    pub request: IacRequest,
    pub is_partial: bool,
}

fn optional<'a>(obj: &'a Map<String, Value>, key: &str) -> Option<&'a Value> {
    obj.get(key).filter(|v| !v.is_null())
}

pub fn parse_iac(body: &Option<Value>, kind: IacKind) -> ApiResult<ParsedIac> {
    let mut errs = Errors::default();
    let Some(obj) = v::model_body(&mut errs, body) else {
        return Err(ApiError::Validation(errs.0));
    };
    let raw = Value::Object(obj.clone());

    let session_id: Option<Uuid> =
        optional(obj, "session_id").and_then(|x| v::uuid(&mut errs, &loc(&["body", "session_id"]), x));
    let repo_uri: Option<String> =
        optional(obj, "repo_uri").and_then(|x| repo_uri_field(&mut errs, &loc(&["body", "repo_uri"]), x));
    let scope_id: Option<String> =
        optional(obj, "scope_id").and_then(|x| v::string(&mut errs, &loc(&["body", "scope_id"]), x, Some(1), None));
    let terraform_provider: Option<TerraformProvider> = optional(obj, "terraform_providers").and_then(|x| {
        v::enumeration(
            &mut errs,
            &loc(&["body", "terraform_providers"]),
            x,
            TerraformProvider::from_value,
            TerraformProvider::expected(),
        )
    });
    let iac_path: Option<String> = match obj.get("iac_path") {
        None | Some(Value::Null) => None,
        Some(Value::String(s)) if s.is_empty() => None,
        Some(Value::String(s)) => {
            if s.starts_with('/') || s.split('/').any(|seg| seg == "..") {
                errs.value_error(
                    &loc(&["body", "iac_path"]),
                    "iac_path must be a repo-relative path (not absolute) and must not contain '..' segments",
                    Value::String(s.clone()),
                );
                None
            } else {
                Some(s.clone())
            }
        }
        // The Python before-validator called `.startswith` on it: an
        // AttributeError, which escaped validation as a server error.
        Some(_) => return Err(ApiError::Internal("iac_path validator received a non-string".into())),
    };
    let is_partial = match kind {
        IacKind::Generate => false,
        _ => match obj.get("is_partial") {
            None => false,
            Some(x) => v::boolean(&mut errs, &loc(&["body", "is_partial"]), x).unwrap_or(false),
        },
    };
    let q: Option<String> = match obj.get("q") {
        None => {
            errs.push("missing", &loc(&["body", "q"]), "Field required", raw.clone(), None);
            None
        }
        Some(x) => v::string(&mut errs, &loc(&["body", "q"]), x, Some(1), None),
    };
    if !errs.is_empty() {
        return Err(ApiError::Validation(errs.0));
    }
    let q = q.unwrap_or_default();
    let body_loc = loc(&["body"]);

    // BaseIacRequest._exactly_one_of_uri_or_session
    let has_uri = repo_uri.is_some();
    let has_sid = session_id.is_some();
    let fail = |msg: &str| {
        let mut e = Errors::default();
        e.value_error(&body_loc, msg, raw.clone());
        Err(ApiError::Validation(e.0))
    };
    if has_uri == has_sid {
        return fail("Exactly one of `repo_uri` or `session_id` must be provided.");
    }
    if has_uri && terraform_provider.is_none() {
        return fail("First call (repo_uri) requires `terraform_providers`.");
    }
    if has_uri && scope_id.is_none() {
        return fail("First call (repo_uri) requires `scope_id`.");
    }
    if has_sid && iac_path.is_some() {
        return fail("iac_path is set only on the first call; iteration calls inherit it from the session.");
    }
    match kind {
        IacKind::Generate => {}
        IacKind::Drift => {
            if is_partial && pyfmt::strip(&q).is_empty() {
                return fail("Partial drift detection requires a non-empty `q`.");
            }
        }
        IacKind::Import => {
            if has_uri && scope_id.as_deref().is_none_or(|s| pyfmt::strip(s).is_empty()) {
                return fail("The `scope_id` must be provided when `repo_uri` is set.");
            }
            if is_partial && pyfmt::strip(&q).is_empty() {
                return fail("Partial import requires a non-empty `q`.");
            }
        }
    }

    let request = match (repo_uri, session_id) {
        (Some(repo_uri), None) => IacRequest::First(FirstCall {
            repo_uri,
            scope_id: scope_id.unwrap_or_default(),
            terraform_provider: terraform_provider.expect("checked above"),
            iac_path,
            q,
        }),
        (None, Some(session_id)) => IacRequest::Iteration { session_id, q },
        _ => unreachable!("exactly one of repo_uri / session_id"),
    };
    Ok(ParsedIac { request, is_partial })
}

/// `ApplyRequest`: an existing session id.
pub fn parse_apply(body: &Option<Value>) -> ApiResult<IacRequest> {
    let mut errs = Errors::default();
    let Some(obj) = v::model_body(&mut errs, body) else {
        return Err(ApiError::Validation(errs.0));
    };
    let session_id = match obj.get("session_id") {
        None => {
            errs.push(
                "missing",
                &loc(&["body", "session_id"]),
                "Field required",
                Value::Object(obj.clone()),
                None,
            );
            None
        }
        Some(x) => v::uuid(&mut errs, &loc(&["body", "session_id"]), x),
    };
    errs.finish()?;
    Ok(IacRequest::Session {
        session_id: session_id.expect("validated"),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::api::validation::parse_body;
    use axum::http::HeaderMap;

    /// Replay every IaC-request case of the FastAPI error catalog.
    #[test]
    fn matches_fastapi_catalog() {
        let catalog: Vec<Value> =
            serde_json::from_str(include_str!("../../testdata/fastapi_validation_errors.json")).unwrap();
        let mut checked = 0;
        for case in catalog {
            let path = case["path"].as_str().unwrap();
            let kind = match path {
                "/v1/iac/generate" => Some(IacKind::Generate),
                "/v1/iac/drift" => Some(IacKind::Drift),
                "/v1/iac/import" => Some(IacKind::Import),
                _ => None,
            };
            let bytes = if case["body"].is_null() {
                Vec::new()
            } else {
                serde_json::to_vec(&case["body"]).unwrap()
            };
            let body = parse_body(&HeaderMap::new(), &bytes).unwrap();
            let outcome = match (kind, path) {
                (Some(k), _) => parse_iac(&body, k).map(|_| ()),
                (None, "/v1/iac/apply") => parse_apply(&body).map(|_| ()),
                _ => continue,
            };
            let expected: Value = serde_json::from_str(case["response"].as_str().unwrap()).unwrap();
            match outcome {
                Err(ApiError::Validation(errs)) => {
                    assert_eq!(serde_json::json!({"detail": errs}), expected, "{path} {}", case["body"])
                }
                other => panic!("{path} {}: expected 422, got {other:?}", case["body"]),
            }
            checked += 1;
        }
        assert!(checked >= 20, "checked {checked}");
    }

    #[test]
    fn valid_first_call() {
        let body = Some(serde_json::json!({
            "q": "x", "repo_uri": " https://org@dev.azure.com/org/p/_git/r ", "terraform_providers": "azure", "scope_id": "s", "iac_path": ""
        }));
        let parsed = parse_iac(&body, IacKind::Generate).unwrap();
        let first = parsed.request.first_call().unwrap();
        assert_eq!(first.repo_uri, "https://org@dev.azure.com/org/p/_git/r");
        assert_eq!(first.iac_path, None);
    }
}
