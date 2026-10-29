// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! The structured reports the sentinel tools build, validated the way
//! pydantic validated them: lax scalar coercion, extra keys ignored,
//! defaults filled in, and every error reported as pydantic's
//! `ValidationError.json()` so the agent can fix its call.

use serde_json::{Map, Number, Value, json};

const PYDANTIC_DOCS: &str = "https://errors.pydantic.dev/2.13/v/";

#[derive(Debug, Clone)]
pub enum Field {
    Str,
    Int,
    Float,
    Bool,
    Literal(&'static [&'static str]),
    Optional(Box<Field>),
    List(Box<Field>),
    Model(&'static Model),
}

#[derive(Debug, Clone)]
pub struct Model {
    pub name: &'static str,
    /// (name, type, default)
    pub fields: &'static [(&'static str, FieldDef)],
}

#[derive(Debug, Clone)]
pub struct FieldDef {
    pub kind: fn() -> Field,
    /// JSON default; `None` means required.
    pub default: Option<fn() -> Value>,
}

const fn req(kind: fn() -> Field) -> FieldDef {
    FieldDef { kind, default: None }
}

const fn opt(kind: fn() -> Field, default: fn() -> Value) -> FieldDef {
    FieldDef {
        kind,
        default: Some(default),
    }
}

fn null() -> Value {
    Value::Null
}

fn empty_list() -> Value {
    json!([])
}

fn empty_str() -> Value {
    json!("")
}

struct Errors(Vec<Value>);

impl Errors {
    fn push(&mut self, kind: &str, loc: &[Value], msg: String, input: &Value, ctx: Option<Value>) {
        let mut e = Map::new();
        e.insert("type".into(), json!(kind));
        e.insert("loc".into(), Value::Array(loc.to_vec()));
        e.insert("msg".into(), json!(msg));
        e.insert("input".into(), input.clone());
        if let Some(c) = ctx {
            e.insert("ctx".into(), c);
        }
        e.insert("url".into(), json!(format!("{PYDANTIC_DOCS}{kind}")));
        self.0.push(Value::Object(e));
    }
}

fn expected_literal(options: &[&str]) -> String {
    let quoted: Vec<String> = options.iter().map(|o| format!("'{o}'")).collect();
    match quoted.len() {
        0 => String::new(),
        1 => quoted[0].clone(),
        n => format!("{} or {}", quoted[..n - 1].join(", "), quoted[n - 1]),
    }
}

fn validate(field: &Field, v: &Value, loc: &mut Vec<Value>, errs: &mut Errors) -> Option<Value> {
    match field {
        Field::Str => match v {
            Value::String(_) => Some(v.clone()),
            _ => {
                errs.push("string_type", loc, "Input should be a valid string".into(), v, None);
                None
            }
        },
        Field::Int => match v {
            Value::Bool(b) => Some(json!(i64::from(*b))),
            Value::Number(n) if n.is_i64() || n.is_u64() => Some(v.clone()),
            Value::Number(n) => {
                let f = n.as_f64().unwrap_or(f64::NAN);
                if f.is_finite() && f.fract() == 0.0 {
                    Some(json!(f as i64))
                } else {
                    errs.push(
                        "int_from_float",
                        loc,
                        "Input should be a valid integer, got a number with a fractional part".into(),
                        v,
                        None,
                    );
                    None
                }
            }
            Value::String(s) => match crate::shared::pyfmt::strip(s).parse::<i64>() {
                Ok(i) => Some(json!(i)),
                Err(_) => {
                    errs.push(
                        "int_parsing",
                        loc,
                        "Input should be a valid integer, unable to parse string as an integer".into(),
                        v,
                        None,
                    );
                    None
                }
            },
            _ => {
                errs.push("int_type", loc, "Input should be a valid integer".into(), v, None);
                None
            }
        },
        Field::Float => match v {
            Value::Bool(b) => Some(json!(if *b { 1.0 } else { 0.0 })),
            Value::Number(n) => Number::from_f64(n.as_f64().unwrap_or(0.0)).map(Value::Number),
            Value::String(s) => match crate::shared::pyfmt::strip(s).parse::<f64>() {
                Ok(f) => Number::from_f64(f).map(Value::Number),
                Err(_) => {
                    errs.push(
                        "float_parsing",
                        loc,
                        "Input should be a valid number, unable to parse string as a number".into(),
                        v,
                        None,
                    );
                    None
                }
            },
            _ => {
                errs.push("float_type", loc, "Input should be a valid number".into(), v, None);
                None
            }
        },
        Field::Bool => {
            let parsed = match v {
                Value::Bool(b) => Some(*b),
                Value::Number(n) => match n.as_f64() {
                    Some(0.0) => Some(false),
                    Some(1.0) => Some(true),
                    _ => None,
                },
                Value::String(s) => match s.to_lowercase().as_str() {
                    "0" | "off" | "f" | "false" | "n" | "no" => Some(false),
                    "1" | "on" | "t" | "true" | "y" | "yes" => Some(true),
                    _ => None,
                },
                _ => {
                    errs.push("bool_type", loc, "Input should be a valid boolean".into(), v, None);
                    return None;
                }
            };
            match parsed {
                Some(b) => Some(json!(b)),
                None => {
                    errs.push(
                        "bool_parsing",
                        loc,
                        "Input should be a valid boolean, unable to interpret input".into(),
                        v,
                        None,
                    );
                    None
                }
            }
        }
        Field::Literal(options) => match v {
            Value::String(s) if options.contains(&s.as_str()) => Some(v.clone()),
            _ => {
                let expected = expected_literal(options);
                errs.push(
                    "literal_error",
                    loc,
                    format!("Input should be {expected}"),
                    v,
                    Some(json!({"expected": expected})),
                );
                None
            }
        },
        Field::Optional(inner) => {
            if v.is_null() {
                Some(Value::Null)
            } else {
                validate(inner, v, loc, errs)
            }
        }
        Field::List(inner) => match v {
            Value::Array(items) => {
                let mut out = Vec::new();
                let mut ok = true;
                for (i, item) in items.iter().enumerate() {
                    loc.push(json!(i));
                    match validate(inner, item, loc, errs) {
                        Some(x) => out.push(x),
                        None => ok = false,
                    }
                    loc.pop();
                }
                ok.then_some(Value::Array(out))
            }
            _ => {
                errs.push("list_type", loc, "Input should be a valid list".into(), v, None);
                None
            }
        },
        Field::Model(model) => validate_model_at(model, v, loc, errs),
    }
}

fn validate_model_at(model: &Model, v: &Value, loc: &mut Vec<Value>, errs: &mut Errors) -> Option<Value> {
    let Value::Object(input) = v else {
        errs.push(
            "model_type",
            loc,
            format!("Input should be a valid dictionary or instance of {}", model.name),
            v,
            Some(json!({"class_name": model.name})),
        );
        return None;
    };
    let mut out = Map::new();
    let mut ok = true;
    for (name, def) in model.fields {
        loc.push(json!(name));
        match input.get(*name) {
            None => match def.default {
                Some(d) => {
                    out.insert((*name).into(), d());
                }
                None => {
                    errs.push("missing", loc, "Field required".into(), v, None);
                    ok = false;
                }
            },
            Some(raw) => match validate(&(def.kind)(), raw, loc, errs) {
                Some(x) => {
                    out.insert((*name).into(), x);
                }
                None => ok = false,
            },
        }
        loc.pop();
    }
    ok.then_some(Value::Object(out))
}

/// Validate `input` against `model`: the `model_dump(mode="json")` of the
/// built instance, or pydantic's error JSON.
pub fn validate_model(model: &Model, input: &Value) -> Result<Value, String> {
    let mut errs = Errors(Vec::new());
    let mut loc = Vec::new();
    match validate_model_at(model, input, &mut loc, &mut errs) {
        Some(v) if errs.0.is_empty() => Ok(v),
        _ => Err(serde_json::to_string(&Value::Array(errs.0)).unwrap_or_default()),
    }
}

macro_rules! f {
    ($e:expr) => {
        || $e
    };
}

// --- plan report ---------------------------------------------------------------

pub static SUMMARY: Model = Model {
    name: "Summary",
    fields: &[
        ("create", req(f!(Field::Int))),
        ("update", req(f!(Field::Int))),
        ("delete", req(f!(Field::Int))),
        ("recreate", req(f!(Field::Int))),
    ],
};
pub static IMPACT_BANNER: Model = Model {
    name: "ImpactBanner",
    fields: &[
        ("level", req(f!(Field::Literal(&["low", "medium", "high"])))),
        ("title", req(f!(Field::Str))),
        ("description", req(f!(Field::Str))),
    ],
};
pub static IMPACT_POINT: Model = Model {
    name: "ImpactPoint",
    fields: &[("title", req(f!(Field::Str))), ("description", req(f!(Field::Str)))],
};
pub static POTENTIAL_IMPACT: Model = Model {
    name: "PotentialImpact",
    fields: &[
        ("banner", req(f!(Field::Model(&IMPACT_BANNER)))),
        ("summary", req(f!(Field::Str))),
        (
            "bullet_points",
            req(f!(Field::List(Box::new(Field::Model(&IMPACT_POINT))))),
        ),
    ],
};
pub static DETAILED_CHANGE: Model = Model {
    name: "DetailedChange",
    fields: &[
        ("name", req(f!(Field::Str))),
        (
            "action",
            req(f!(Field::Literal(&["create", "update", "delete", "recreate"]))),
        ),
        ("notes", req(f!(Field::Str))),
        ("summary", req(f!(Field::Str))),
        ("details", req(f!(Field::Str))),
    ],
};
pub static COST_BREAKDOWN: Model = Model {
    name: "CostBreakdown",
    fields: &[
        ("resource_type", req(f!(Field::Str))),
        (
            "pricing_model",
            req(f!(Field::Literal(&["fixed", "usage_based", "free"]))),
        ),
        ("fixed_monthly_cost", req(f!(Field::Float))),
        ("notes", req(f!(Field::Str))),
    ],
};
pub static ESTIMATED_COSTS: Model = Model {
    name: "EstimatedCosts",
    fields: &[
        ("currency", req(f!(Field::Str))),
        ("total_fixed_monthly_cost", req(f!(Field::Float))),
        ("introduction_paragraph", req(f!(Field::Str))),
        (
            "breakdown",
            req(f!(Field::List(Box::new(Field::Model(&COST_BREAKDOWN))))),
        ),
    ],
};
pub static TERRAFORM_PLAN_REPORT: Model = Model {
    name: "TerraformPlanReport",
    fields: &[
        ("summary", req(f!(Field::Model(&SUMMARY)))),
        (
            "detailed_changes",
            req(f!(Field::List(Box::new(Field::Model(&DETAILED_CHANGE))))),
        ),
        ("potential_impact", req(f!(Field::Model(&POTENTIAL_IMPACT)))),
        ("estimated_costs", req(f!(Field::Model(&ESTIMATED_COSTS)))),
    ],
};

// --- drift report ----------------------------------------------------------------

pub static DRIFT_CHANGE: Model = Model {
    name: "TerraformDriftChange",
    fields: &[
        ("attribute_modified", req(f!(Field::Str))),
        ("change_description", req(f!(Field::Str))),
        ("details", opt(f!(Field::List(Box::new(Field::Str))), empty_list)),
        ("reason", req(f!(Field::Str))),
    ],
};
pub static DRIFT_RESOURCE: Model = Model {
    name: "TerraformDriftResource",
    fields: &[
        ("file_path", req(f!(Field::Str))),
        ("resource_address", req(f!(Field::Str))),
        ("changes", req(f!(Field::List(Box::new(Field::Model(&DRIFT_CHANGE)))))),
    ],
};
pub static DRIFT_UNRECONCILED: Model = Model {
    name: "TerraformDriftUnreconciled",
    fields: &[
        ("resource_address", opt(f!(Field::Str), empty_str)),
        ("reason", req(f!(Field::Str))),
        ("details", opt(f!(Field::List(Box::new(Field::Str))), empty_list)),
    ],
};
pub static DRIFT_EXCEPTION: Model = Model {
    name: "TerraformDriftException",
    fields: &[
        ("resource_address", opt(f!(Field::Str), empty_str)),
        ("change", req(f!(Field::Str))),
        ("rule", req(f!(Field::Str))),
    ],
};
pub static TERRAFORM_DRIFT_REPORT: Model = Model {
    name: "TerraformDriftReport",
    fields: &[
        ("summary", req(f!(Field::Str))),
        ("status", req(f!(Field::Literal(&["Succeeded", "Partial", "Failed"])))),
        (
            "remediated_resources",
            req(f!(Field::List(Box::new(Field::Model(&DRIFT_RESOURCE))))),
        ),
        (
            "unreconciled_drift",
            opt(f!(Field::List(Box::new(Field::Model(&DRIFT_UNRECONCILED)))), empty_list),
        ),
        (
            "whitelisted_exceptions",
            opt(f!(Field::List(Box::new(Field::Model(&DRIFT_EXCEPTION)))), empty_list),
        ),
    ],
};

// --- apply report ------------------------------------------------------------------

pub static APPLY_CHANGE: Model = Model {
    name: "TerraformApplyChange",
    fields: &[
        ("resource_type", req(f!(Field::Str))),
        ("resource_name", req(f!(Field::Str))),
        (
            "action",
            req(f!(Field::Literal(&["created", "updated", "destroyed", "no_change"]))),
        ),
        ("status", req(f!(Field::Literal(&["success", "failed"])))),
        ("details", req(f!(Field::Str))),
        ("error_message", opt(f!(Field::Optional(Box::new(Field::Str))), null)),
    ],
};
pub static APPLY_SUMMARY: Model = Model {
    name: "TerraformApplySummary",
    fields: &[
        ("total_resources", req(f!(Field::Int))),
        ("created", req(f!(Field::Int))),
        ("updated", req(f!(Field::Int))),
        ("destroyed", req(f!(Field::Int))),
        ("failed", req(f!(Field::Int))),
    ],
};
pub static TERRAFORM_APPLY_REPORT: Model = Model {
    name: "TerraformApplyReport",
    fields: &[
        ("summary", req(f!(Field::Model(&APPLY_SUMMARY)))),
        ("status", req(f!(Field::Literal(&["Success", "Partial", "Failed"])))),
        ("execution_summary", req(f!(Field::Str))),
        (
            "resource_changes",
            req(f!(Field::List(Box::new(Field::Model(&APPLY_CHANGE))))),
        ),
        ("recommendations", req(f!(Field::List(Box::new(Field::Str))))),
    ],
};

// --- import report -------------------------------------------------------------------

pub static IMPORTED_RESOURCE: Model = Model {
    name: "TerraformImportedResource",
    fields: &[
        ("resource_address", req(f!(Field::Str))),
        ("resource_id", req(f!(Field::Str))),
        ("status", req(f!(Field::Literal(&["imported", "failed"])))),
        ("details", req(f!(Field::Str))),
        ("error_message", opt(f!(Field::Optional(Box::new(Field::Str))), null)),
    ],
};
pub static EXCLUDED_RESOURCE: Model = Model {
    name: "TerraformExcludedResource",
    fields: &[("resource_id", req(f!(Field::Str))), ("details", req(f!(Field::Str)))],
};
pub static IMPORT_SUMMARY: Model = Model {
    name: "TerraformImportSummary",
    fields: &[
        ("selected", req(f!(Field::Int))),
        ("imported", req(f!(Field::Int))),
        ("failed", req(f!(Field::Int))),
    ],
};
pub static TERRAFORM_IMPORT_REPORT: Model = Model {
    name: "TerraformImportReport",
    fields: &[
        ("summary", req(f!(Field::Model(&IMPORT_SUMMARY)))),
        ("status", req(f!(Field::Literal(&["Succeeded", "Partial", "Failed"])))),
        ("execution_summary", req(f!(Field::Str))),
        (
            "imported_resources",
            req(f!(Field::List(Box::new(Field::Model(&IMPORTED_RESOURCE))))),
        ),
        (
            "excluded_resources",
            req(f!(Field::List(Box::new(Field::Model(&EXCLUDED_RESOURCE))))),
        ),
        ("state_alignment", req(f!(Field::Str))),
        ("recommendations", req(f!(Field::List(Box::new(Field::Str))))),
    ],
};

// --- compliance / reconciliation --------------------------------------------------------

pub static COMPLIANCE_VIOLATION: Model = Model {
    name: "ComplianceViolation",
    fields: &[
        ("rule_id", req(f!(Field::Str))),
        (
            "severity",
            req(f!(Field::Literal(&["info", "warning", "error", "critical"]))),
        ),
        ("resource", opt(f!(Field::Optional(Box::new(Field::Str))), null)),
        ("message", req(f!(Field::Str))),
        ("suggested_fix", opt(f!(Field::Optional(Box::new(Field::Str))), null)),
    ],
};
pub static COMPLIANCE_CHECK_REPORT: Model = Model {
    name: "ComplianceCheckReport",
    fields: &[
        ("passed", req(f!(Field::Bool))),
        (
            "violations",
            req(f!(Field::List(Box::new(Field::Model(&COMPLIANCE_VIOLATION))))),
        ),
        ("summary", req(f!(Field::Str))),
        ("checked_rules", req(f!(Field::List(Box::new(Field::Str))))),
    ],
};

pub static RECONCILIATION_CHANGE: Model = Model {
    name: "ReconciliationChange",
    fields: &[
        ("description", req(f!(Field::Str))),
        ("reverts_session_change", req(f!(Field::Bool))),
        ("reason", req(f!(Field::Str))),
    ],
};
pub static RECONCILIATION_VERDICT: Model = Model {
    name: "ReconciliationVerdict",
    fields: &[
        ("index", req(f!(Field::Int))),
        (
            "changes",
            req(f!(Field::List(Box::new(Field::Model(&RECONCILIATION_CHANGE))))),
        ),
        ("operation", opt(f!(Field::Str), empty_str)),
    ],
};
pub static RECONCILIATION_REPORT: Model = Model {
    name: "ReconciliationReport",
    fields: &[(
        "verdicts",
        req(f!(Field::List(Box::new(Field::Model(&RECONCILIATION_VERDICT))))),
    )],
};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fills_defaults_and_coerces() {
        let v = validate_model(
            &TERRAFORM_DRIFT_REPORT,
            &json!({"summary": "s", "status": "Partial", "remediated_resources": [
                {"file_path": "a.tf", "resource_address": "x.y", "changes": [{"attribute_modified": "tags", "change_description": "d", "reason": "r"}]}
            ], "extra": 1}),
        )
        .unwrap();
        assert_eq!(v["remediated_resources"][0]["changes"][0]["details"], json!([]));
        assert_eq!(v["unreconciled_drift"], json!([]));
        assert!(v.get("extra").is_none());
        let costs = validate_model(
            &ESTIMATED_COSTS,
            &json!({"currency": "USD", "total_fixed_monthly_cost": 5, "introduction_paragraph": "i", "breakdown": []}),
        )
        .unwrap();
        assert_eq!(
            serde_json::to_string(&costs["total_fixed_monthly_cost"]).unwrap(),
            "5.0"
        );
    }

    #[test]
    fn pydantic_error_json() {
        let err = validate_model(&SUMMARY, &json!({"create": 1, "update": "x", "delete": 2.5})).unwrap_err();
        assert_eq!(
            err,
            r#"[{"type":"int_parsing","loc":["update"],"msg":"Input should be a valid integer, unable to parse string as an integer","input":"x","url":"https://errors.pydantic.dev/2.13/v/int_parsing"},{"type":"int_from_float","loc":["delete"],"msg":"Input should be a valid integer, got a number with a fractional part","input":2.5,"url":"https://errors.pydantic.dev/2.13/v/int_from_float"},{"type":"missing","loc":["recreate"],"msg":"Field required","input":{"create":1,"update":"x","delete":2.5},"url":"https://errors.pydantic.dev/2.13/v/missing"}]"#
        );
    }

    #[test]
    fn literal_errors_carry_expected() {
        let err = validate_model(
            &IMPACT_BANNER,
            &json!({"level": "huge", "title": "t", "description": "d"}),
        )
        .unwrap_err();
        assert!(
            err.contains(r#""msg":"Input should be 'low', 'medium' or 'high'""#),
            "{err}"
        );
    }
}
