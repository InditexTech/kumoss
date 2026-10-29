// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};

use crate::infrastructure::terraform::deepdiff::deep_diff;
use crate::shared::config::urlsplit;
use crate::shared::error::{AppError, AppResult};
use crate::shared::pyfmt;

/// Identify the Terraform project a session operates on: a digest over the
/// repository, the cloud scope and the root module, independent of where
/// the repository was cloned, so every call and every session on the same
/// project resolves to the same state. The URI is normalized first so a
/// userinfo username, a `.git` suffix or a different case do not split one
/// project into several.
pub fn project_id(repo_uri: &str, scope_id: &str, iac_path: Option<&str>) -> String {
    let seed = [
        normalize_repo_uri(repo_uri),
        pyfmt::strip(scope_id).to_lowercase(),
        normalize_iac_path(iac_path.unwrap_or("")),
    ]
    .join("\n");
    hex::encode(Sha256::digest(seed.as_bytes()))
}

fn normalize_repo_uri(repo_uri: &str) -> String {
    let parsed = urlsplit(pyfmt::strip(repo_uri));
    let host = parsed.hostname.unwrap_or_default().to_lowercase();
    let path = parsed.path.trim_matches('/');
    let path = path.strip_suffix(".git").unwrap_or(path);
    format!("{host}/{}", path.trim_matches('/').to_lowercase())
}

/// `PurePosixPath(path).as_posix()` of the stripped path.
fn normalize_iac_path(iac_path: &str) -> String {
    let path = pyfmt::strip(iac_path).trim_matches('/');
    if path.is_empty() {
        return String::new();
    }
    let parts: Vec<&str> = path.split('/').filter(|p| !p.is_empty() && *p != ".").collect();
    if parts.is_empty() { ".".into() } else { parts.join("/") }
}

/// The plan's resource changes as drift: what the configuration must change
/// to match the infrastructure when `reversed`.
pub fn plan_to_drift(plan_json: &Value, reversed: bool) -> AppResult<Vec<Value>> {
    let format_version = plan_json
        .get("format_version")
        .ok_or_else(|| AppError::missing_key("format_version"))?;
    let version: f64 = match format_version {
        Value::String(s) => pyfmt::strip(s)
            .parse()
            .map_err(|_| AppError::internal(format!("could not convert string to float: {}", pyfmt::repr_str(s))))?,
        Value::Number(n) => n.as_f64().unwrap_or(0.0),
        other => {
            return Err(AppError::internal(format!(
                "float() argument must be a string or a real number, not {other}"
            )));
        }
    };
    if version >= 2.0 {
        return Err(AppError::new("Terraform plan json output major format change.", 500));
    }
    let mut resources = resource_changes(plan_json)?;
    if reversed {
        reverse_output(&mut resources);
    }
    Ok(resources)
}

/// The resources a plan creates in a compartment other than the request's,
/// each as `address (compartment)`. Only plain creations count; the tenancy
/// is where identity resources live, and a compartment still unknown at plan
/// time is one the same plan creates.
pub fn oci_creations_outside(plan_json: &Value, compartment_ocid: &str) -> Vec<String> {
    let mut outside = Vec::new();
    let Some(changes) = plan_json.get("resource_changes").and_then(Value::as_array) else {
        return outside;
    };
    for resource in changes {
        let change = resource
            .get("change")
            .filter(|c| !c.is_null())
            .cloned()
            .unwrap_or(json!({}));
        if change.get("actions") != Some(&json!(["create"])) {
            continue;
        }
        let compartment = change.get("after").and_then(|a| a.get("compartment_id"));
        if let Some(Value::String(c)) = compartment
            && c.starts_with("ocid1.compartment.")
            && c != compartment_ocid
        {
            let address = pyfmt::str_value(resource.get("address").unwrap_or(&Value::Null));
            outside.push(format!("{address} ({c})"));
        }
    }
    outside
}

fn actions_of(resource: &Value) -> AppResult<Vec<Value>> {
    resource
        .get("change")
        .and_then(|c| c.get("actions"))
        .and_then(Value::as_array)
        .cloned()
        .ok_or_else(|| AppError::missing_key("actions"))
}

fn resource_changes(plan: &Value) -> AppResult<Vec<Value>> {
    let Some(changes) = plan.get("resource_changes").filter(|v| match v {
        Value::Array(a) => !a.is_empty(),
        Value::Null => false,
        _ => true,
    }) else {
        return Ok(Vec::new());
    };
    let changes = changes.as_array().cloned().unwrap_or_default();
    let mut changed = Vec::new();
    for resource in &changes {
        let actions = actions_of(resource)?;
        let first = actions
            .first()
            .ok_or_else(|| AppError::internal("list index out of range"))?;
        if first == "update" || first == "create" || first == "delete" {
            changed.push(resource.clone());
        }
    }
    let mut filtered = Vec::new();
    for resource in &changed {
        let actions = actions_of(resource)?;
        let address = resource
            .get("address")
            .cloned()
            .ok_or_else(|| AppError::missing_key("address"))?;
        let change = &resource["change"];
        if actions == [json!("update")]
            || actions == [json!("delete"), json!("create")]
            || actions == [json!("create"), json!("delete")]
        {
            let before = change.get("before").ok_or_else(|| AppError::missing_key("before"))?;
            let after = change.get("after").ok_or_else(|| AppError::missing_key("after"))?;
            let diff = deep_diff(before, after);
            if diff.as_object().is_some_and(|m| !m.is_empty()) {
                filtered.push(json!({"address": address, "action": "update resource", "changes": diff}));
            }
        } else if actions == [json!("create")] {
            filtered.push(json!({"address": address, "action": "delete resource"}));
        } else if actions == [json!("delete")] {
            let before = change.get("before").ok_or_else(|| AppError::missing_key("before"))?;
            filtered.push(json!({"address": address, "action": "create resource", "changes": before}));
        }
    }
    Ok(filtered)
}

fn swap_word(key: &str, pair: (&str, &str)) -> String {
    let (a, b) = pair;
    key.split('_')
        .map(|p| {
            if p == a {
                b
            } else if p == b {
                a
            } else {
                p
            }
        })
        .collect::<Vec<_>>()
        .join("_")
}

fn reverse_items(items: &Value) -> Value {
    let Some(map) = items.as_object() else {
        return items.clone();
    };
    let mut out = Map::new();
    for (path, change) in map {
        let reversed = match change.as_object() {
            Some(fields) => {
                let mut m = Map::new();
                for (field, value) in fields {
                    m.insert(swap_word(field, ("old", "new")), value.clone());
                }
                Value::Object(m)
            }
            None => change.clone(),
        };
        out.insert(path.clone(), reversed);
    }
    Value::Object(out)
}

fn reverse_output(changes: &mut [Value]) {
    for resource in changes.iter_mut() {
        if resource["action"] != "update resource" {
            continue;
        }
        let Some(categories) = resource["changes"].as_object().cloned() else {
            continue;
        };
        let mut out = Map::new();
        for (category, items) in &categories {
            let value = if category == "values_changed" || category == "type_changes" {
                reverse_items(items)
            } else {
                items.clone()
            };
            out.insert(swap_word(category, ("added", "removed")), value);
        }
        resource["changes"] = Value::Object(out);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn project_id_normalizes() {
        let a = project_id("https://User@GitHub.com/Org/Repo.git/", " SUB ", Some("/envs/dev/"));
        let b = project_id("https://github.com/org/repo", "sub", Some("envs/dev"));
        assert_eq!(a, b);
        let seed = "github.com/org/repo\nsub\nenvs/dev";
        assert_eq!(b, hex::encode(Sha256::digest(seed.as_bytes())));
        assert_eq!(normalize_iac_path("./a//./b/"), "a/b");
        assert_eq!(normalize_iac_path("."), ".");
        assert_eq!(normalize_iac_path(""), "");
    }

    #[test]
    fn drift_is_reversed() {
        let plan = json!({
            "format_version": "1.2",
            "resource_changes": [
                {"address": "a.b", "change": {"actions": ["update"], "before": {"x": 1, "y": "old"}, "after": {"x": 1, "y": "new", "z": 2}}},
                {"address": "c.d", "change": {"actions": ["create"], "before": null, "after": {}}},
                {"address": "e.f", "change": {"actions": ["delete"], "before": {"k": "v"}, "after": null}},
                {"address": "g.h", "change": {"actions": ["no-op"], "before": {}, "after": {}}}
            ]
        });
        let drift = plan_to_drift(&plan, true).unwrap();
        assert_eq!(
            Value::Array(drift),
            json!([
                {"address": "a.b", "action": "update resource", "changes": {
                    "dictionary_item_removed": {"root['z']": 2},
                    "values_changed": {"root['y']": {"old_value": "new", "new_value": "old"}}
                }},
                {"address": "c.d", "action": "delete resource"},
                {"address": "e.f", "action": "create resource", "changes": {"k": "v"}}
            ])
        );
    }

    #[test]
    fn major_format_change_is_refused() {
        assert!(plan_to_drift(&json!({"format_version": "2.0"}), true).is_err());
    }

    #[test]
    fn oci_outside_compartment() {
        let plan = json!({"resource_changes": [
            {"address": "oci_x.a", "change": {"actions": ["create"], "after": {"compartment_id": "ocid1.compartment.oc1..other"}}},
            {"address": "oci_x.b", "change": {"actions": ["create"], "after": {"compartment_id": "ocid1.compartment.oc1..mine"}}},
            {"address": "oci_x.c", "change": {"actions": ["create"], "after": {"compartment_id": "ocid1.tenancy.oc1..root"}}}
        ]});
        assert_eq!(
            oci_creations_outside(&plan, "ocid1.compartment.oc1..mine"),
            vec!["oci_x.a (ocid1.compartment.oc1..other)"]
        );
    }
}
