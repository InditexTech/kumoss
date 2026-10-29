// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! `yaml.safe_load` semantics on top of yaml-rust2's event parser.
//!
//! config.yaml and the prompt seeds were written against PyYAML, which
//! implements YAML 1.1: `yes`/`on` are booleans, `0755` is octal, `1:30`
//! is sexagesimal. yaml-rust2 resolves plain scalars by YAML 1.2 rules, so
//! scalars are resolved here from the raw events with PyYAML's implicit
//! resolvers instead.

use std::collections::HashMap;
use std::sync::LazyLock;

use regex::Regex;
use serde_json::{Map, Number, Value};
use yaml_rust2::parser::{Event, MarkedEventReceiver, Parser};
use yaml_rust2::scanner::{Marker, TScalarStyle};

/// Marker key for a YAML timestamp: PyYAML builds a `datetime`, which no
/// string or number field accepts, so it must not read as a plain string.
pub const TIMESTAMP_KEY: &str = "__yaml_timestamp__";

static BOOL_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:yes|Yes|YES|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF)$").unwrap()
});
static FLOAT_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+][0-9]+)?|\.[0-9][0-9_]*(?:[eE][-+][0-9]+)?|[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$",
    )
    .unwrap()
});
static INT_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"^(?:[-+]?0b[0-1_]+|[-+]?0[0-7_]+|[-+]?(?:0|[1-9][0-9_]*)|[-+]?0x[0-9a-fA-F_]+|[-+]?[1-9][0-9_]*(?::[0-5]?[0-9])+)$",
    )
    .unwrap()
});
static NULL_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^(?:~|null|Null|NULL|)$").unwrap());
static TIMESTAMP_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        r"^(?:[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]|[0-9][0-9][0-9][0-9]-[0-9][0-9]?-[0-9][0-9]?(?:[Tt]|[ \t]+)[0-9][0-9]?:[0-9][0-9]:[0-9][0-9](?:\.[0-9]*)?(?:[ \t]*(?:Z|[-+][0-9][0-9]?(?::[0-9][0-9])?))?)$",
    )
    .unwrap()
});

#[derive(Debug)]
pub struct YamlError(pub String);

impl std::fmt::Display for YamlError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

fn sexagesimal(parts: &str) -> f64 {
    let mut value = 0.0;
    for part in parts.split(':') {
        value = value * 60.0 + part.parse::<f64>().unwrap_or(0.0);
    }
    value
}

fn construct_int(raw: &str) -> Value {
    let cleaned = raw.replace('_', "");
    let (sign, body) = match cleaned.strip_prefix('-') {
        Some(rest) => (-1i128, rest.to_string()),
        None => (1i128, cleaned.strip_prefix('+').unwrap_or(&cleaned).to_string()),
    };
    let magnitude: i128 = if body == "0" {
        0
    } else if let Some(bits) = body.strip_prefix("0b") {
        i128::from_str_radix(bits, 2).unwrap_or(0)
    } else if let Some(hex) = body.strip_prefix("0x") {
        i128::from_str_radix(hex, 16).unwrap_or(0)
    } else if body.starts_with('0') {
        i128::from_str_radix(&body, 8).unwrap_or(0)
    } else if body.contains(':') {
        let mut v: i128 = 0;
        for part in body.split(':') {
            v = v * 60 + part.parse::<i128>().unwrap_or(0);
        }
        v
    } else {
        body.parse::<i128>().unwrap_or(0)
    };
    let n = sign * magnitude;
    if let Ok(v) = i64::try_from(n) {
        Value::Number(Number::from(v))
    } else if let Ok(v) = u64::try_from(n) {
        Value::Number(Number::from(v))
    } else {
        Number::from_f64(n as f64).map(Value::Number).unwrap_or(Value::Null)
    }
}

fn construct_float(raw: &str) -> Value {
    let cleaned = raw.replace('_', "").to_lowercase();
    let (sign, body) = match cleaned.strip_prefix('-') {
        Some(rest) => (-1.0, rest.to_string()),
        None => (1.0, cleaned.strip_prefix('+').unwrap_or(&cleaned).to_string()),
    };
    let v = if body == ".inf" {
        f64::INFINITY
    } else if body == ".nan" {
        f64::NAN
    } else if body.contains(':') {
        sexagesimal(&body)
    } else {
        body.parse::<f64>().unwrap_or(0.0)
    };
    // JSON has no inf/nan; neither appears in a config field that accepts it.
    Number::from_f64(sign * v).map(Value::Number).unwrap_or(Value::Null)
}

/// PyYAML's implicit resolution of a plain scalar.
fn resolve_plain(raw: &str) -> Value {
    let first = raw.chars().next();
    let candidates: &[&str] = match first {
        None => &["null"],
        Some('y' | 'Y' | 'n' | 'N' | 't' | 'T' | 'f' | 'F' | 'o' | 'O') => &["bool", "null"],
        Some('-' | '+') => &["float", "int"],
        Some('0'..='9') => &["float", "int", "timestamp"],
        Some('.') => &["float"],
        Some('~') => &["null"],
        _ => &[],
    };
    for kind in candidates {
        match *kind {
            "bool" if BOOL_RE.is_match(raw) => {
                return Value::Bool(matches!(raw.to_lowercase().as_str(), "yes" | "true" | "on"));
            }
            "float" if FLOAT_RE.is_match(raw) => return construct_float(raw),
            "int" if INT_RE.is_match(raw) => return construct_int(raw),
            "null" if NULL_RE.is_match(raw) => return Value::Null,
            "timestamp" if TIMESTAMP_RE.is_match(raw) => {
                let mut m = Map::new();
                m.insert(TIMESTAMP_KEY.into(), Value::String(raw.into()));
                return Value::Object(m);
            }
            _ => {}
        }
    }
    Value::String(raw.to_string())
}

fn resolve_tagged(raw: &str, suffix: &str) -> Value {
    match suffix {
        "str" => Value::String(raw.into()),
        "int" => construct_int(raw),
        "float" => construct_float(raw),
        "bool" => Value::Bool(matches!(raw.to_lowercase().as_str(), "yes" | "true" | "on")),
        "null" => Value::Null,
        _ => Value::String(raw.into()),
    }
}

enum Frame {
    Seq(Vec<Value>, usize),
    Map(Map<String, Value>, Option<String>, usize, Vec<Value>),
}

#[derive(Default)]
struct Composer {
    stack: Vec<Frame>,
    anchors: HashMap<usize, Value>,
    documents: Vec<Value>,
    error: Option<String>,
}

fn key_string(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        other => crate::shared::pyfmt::str_value(other),
    }
}

impl Composer {
    fn push_value(&mut self, value: Value, anchor: usize) {
        if anchor > 0 {
            self.anchors.insert(anchor, value.clone());
        }
        match self.stack.last_mut() {
            None => self.documents.push(value),
            Some(Frame::Seq(items, _)) => items.push(value),
            Some(Frame::Map(map, pending, _, merges)) => match pending.take() {
                None => *pending = Some(key_string(&value)),
                Some(key) if key == "<<" => merges.push(value),
                Some(key) => {
                    map.insert(key, value);
                }
            },
        }
    }
}

impl MarkedEventReceiver for Composer {
    fn on_event(&mut self, ev: Event, _mark: Marker) {
        match ev {
            Event::Scalar(raw, style, anchor, tag) => {
                let value = match (&tag, style) {
                    (Some(tag), _) if tag.handle == "tag:yaml.org,2002:" || tag.handle == "!!" => {
                        resolve_tagged(&raw, &tag.suffix)
                    }
                    (_, TScalarStyle::Plain) => resolve_plain(&raw),
                    _ => Value::String(raw),
                };
                self.push_value(value, anchor);
            }
            Event::SequenceStart(anchor, _) => self.stack.push(Frame::Seq(Vec::new(), anchor)),
            Event::SequenceEnd => {
                if let Some(Frame::Seq(items, anchor)) = self.stack.pop() {
                    self.push_value(Value::Array(items), anchor);
                }
            }
            Event::MappingStart(anchor, _) => self.stack.push(Frame::Map(Map::new(), None, anchor, Vec::new())),
            Event::MappingEnd => {
                if let Some(Frame::Map(mut map, _, anchor, merges)) = self.stack.pop() {
                    for merge in merges {
                        let sources = match merge {
                            Value::Array(items) => items,
                            other => vec![other],
                        };
                        for source in sources {
                            if let Value::Object(src) = source {
                                for (k, v) in src {
                                    map.entry(k).or_insert(v);
                                }
                            }
                        }
                    }
                    self.push_value(Value::Object(map), anchor);
                }
            }
            Event::Alias(id) => match self.anchors.get(&id).cloned() {
                Some(v) => self.push_value(v, 0),
                None => self.error = Some(format!("found undefined alias {id}")),
            },
            _ => {}
        }
    }
}

/// `yaml.safe_load(text)`: `Value::Null` for an empty document.
pub fn safe_load(text: &str) -> Result<Value, YamlError> {
    let mut composer = Composer::default();
    let mut parser = Parser::new_from_str(text);
    parser.load(&mut composer, true).map_err(|e| YamlError(e.to_string()))?;
    if let Some(err) = composer.error {
        return Err(YamlError(err));
    }
    match composer.documents.len() {
        0 => Ok(Value::Null),
        1 => Ok(composer.documents.pop().unwrap_or(Value::Null)),
        _ => Err(YamlError(
            "expected a single document in the stream but found another document".into(),
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn yaml_1_1_scalars() {
        let v =
            safe_load("a: yes\nb: off\nc: 0755\nd: 1:30\ne: '0755'\nf: ~\ng:\nh: 1_000\ni: 1.5\nj: .inf\nk: text\n")
                .unwrap();
        assert_eq!(v["a"], json!(true));
        assert_eq!(v["b"], json!(false));
        assert_eq!(v["c"], json!(493));
        assert_eq!(v["d"], json!(90));
        assert_eq!(v["e"], json!("0755"));
        assert_eq!(v["f"], json!(null));
        assert_eq!(v["g"], json!(null));
        assert_eq!(v["h"], json!(1000));
        assert_eq!(v["i"], json!(1.5));
        assert_eq!(v["j"], json!(null));
        assert_eq!(v["k"], json!("text"));
    }

    #[test]
    fn block_scalars_and_nesting() {
        let v = safe_load("body: |\n  line one\n  line two\nlist:\n  - x\n  - 2\n").unwrap();
        assert_eq!(v["body"], json!("line one\nline two\n"));
        assert_eq!(v["list"], json!(["x", 2]));
    }

    #[test]
    fn empty_document_is_null() {
        assert_eq!(safe_load("").unwrap(), Value::Null);
        assert_eq!(safe_load("# only a comment\n").unwrap(), Value::Null);
    }

    #[test]
    fn merge_keys_and_aliases() {
        let v = safe_load("base: &b\n  x: 1\n  y: 2\nchild:\n  <<: *b\n  y: 3\n").unwrap();
        assert_eq!(v["child"], json!({"y": 3, "x": 1}));
    }
}
