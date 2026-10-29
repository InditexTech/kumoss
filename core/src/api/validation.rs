// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Request validation with FastAPI/pydantic semantics and error shapes.
//!
//! Errors accumulate in declaration order (path, query, then body) and are
//! answered together as one 422, each entry shaped like pydantic's:
//! `{"type", "loc", "msg", "input", "ctx"?}`.

use std::collections::HashMap;

use axum::http::HeaderMap;
use serde_json::{Map, Value, json};
use uuid::Uuid;

use crate::api::errors::ApiError;
use crate::shared::pyfmt;

#[derive(Default)]
pub struct Errors(pub Vec<Value>);

impl Errors {
    pub fn push(&mut self, kind: &str, loc: &[Value], msg: impl Into<String>, input: Value, ctx: Option<Value>) {
        let mut e = Map::new();
        e.insert("type".into(), json!(kind));
        e.insert("loc".into(), Value::Array(loc.to_vec()));
        e.insert("msg".into(), json!(msg.into()));
        e.insert("input".into(), input);
        if let Some(c) = ctx {
            e.insert("ctx".into(), c);
        }
        self.0.push(Value::Object(e));
    }

    /// A model validator's `ValueError`, reported on the whole body.
    pub fn value_error(&mut self, loc: &[Value], msg: &str, input: Value) {
        self.push(
            "value_error",
            loc,
            format!("Value error, {msg}"),
            input,
            Some(json!({"error": {}})),
        );
    }

    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }

    pub fn finish(self) -> Result<(), ApiError> {
        if self.0.is_empty() {
            Ok(())
        } else {
            Err(ApiError::Validation(self.0))
        }
    }
}

pub fn loc(parts: &[&str]) -> Vec<Value> {
    parts.iter().map(|p| json!(p)).collect()
}

pub fn loc_with(base: &[Value], key: &str) -> Vec<Value> {
    let mut v = base.to_vec();
    v.push(json!(key));
    v
}

// --- scalar validators ---------------------------------------------------------------

fn char_word(n: usize) -> &'static str {
    if n == 1 { "character" } else { "characters" }
}

/// A `str` field with optional length bounds.
pub fn string(errs: &mut Errors, loc: &[Value], v: &Value, min: Option<usize>, max: Option<usize>) -> Option<String> {
    let Value::String(s) = v else {
        errs.push("string_type", loc, "Input should be a valid string", v.clone(), None);
        return None;
    };
    let len = pyfmt::char_len(s);
    if let Some(min) = min
        && len < min
    {
        errs.push(
            "string_too_short",
            loc,
            format!("String should have at least {min} {}", char_word(min)),
            v.clone(),
            Some(json!({"min_length": min})),
        );
        return None;
    }
    if let Some(max) = max
        && len > max
    {
        errs.push(
            "string_too_long",
            loc,
            format!("String should have at most {max} {}", char_word(max)),
            v.clone(),
            Some(json!({"max_length": max})),
        );
        return None;
    }
    Some(s.clone())
}

pub fn boolean(errs: &mut Errors, loc: &[Value], v: &Value) -> Option<bool> {
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
            errs.push("bool_type", loc, "Input should be a valid boolean", v.clone(), None);
            return None;
        }
    };
    if parsed.is_none() {
        errs.push(
            "bool_parsing",
            loc,
            "Input should be a valid boolean, unable to interpret input",
            v.clone(),
            None,
        );
    }
    parsed
}

pub fn integer(errs: &mut Errors, loc: &[Value], v: &Value) -> Option<i64> {
    match v {
        Value::Number(n) if n.is_i64() => n.as_i64(),
        Value::Number(n) => match n.as_f64() {
            Some(f) if f.fract() == 0.0 && f.is_finite() => Some(f as i64),
            _ => {
                errs.push(
                    "int_from_float",
                    loc,
                    "Input should be a valid integer, got a number with a fractional part",
                    v.clone(),
                    None,
                );
                None
            }
        },
        Value::Bool(b) => Some(i64::from(*b)),
        Value::String(s) => match s.trim().parse::<i64>() {
            Ok(i) => Some(i),
            Err(_) => {
                errs.push(
                    "int_parsing",
                    loc,
                    "Input should be a valid integer, unable to parse string as an integer",
                    v.clone(),
                    None,
                );
                None
            }
        },
        _ => {
            errs.push("int_type", loc, "Input should be a valid integer", v.clone(), None);
            None
        }
    }
}

pub fn uuid(errs: &mut Errors, loc: &[Value], v: &Value) -> Option<Uuid> {
    let Value::String(s) = v else {
        errs.push(
            "uuid_type",
            loc,
            "UUID input should be a string, bytes or UUID object",
            v.clone(),
            None,
        );
        return None;
    };
    match Uuid::parse_str(s) {
        Ok(u) => Some(u),
        Err(_) => {
            let detail = uuid_error_detail(s);
            errs.push(
                "uuid_parsing",
                loc,
                format!("Input should be a valid UUID, {detail}"),
                v.clone(),
                Some(json!({"error": detail})),
            );
            None
        }
    }
}

/// Why `raw` is not a UUID, worded like the uuid crate version pydantic-core
/// links (1-based positions): the input is re-scanned for the first invalid
/// character, then the group structure is checked.
pub fn uuid_error_detail(raw: &str) -> String {
    let bytes = raw.as_bytes();
    let (body, offset, simple): (&str, usize, bool) =
        if bytes.len() >= 2 && bytes[0] == b'{' && bytes[bytes.len() - 1] == b'}' {
            (&raw[1..raw.len() - 1], 1, false)
        } else if let Some(rest) = raw.strip_prefix("urn:uuid:") {
            (rest, "urn:uuid:".len(), false)
        } else {
            (raw, 0, true)
        };
    let mut hyphens = 0usize;
    let mut bounds = [0usize; 4];
    for (index, c) in body.char_indices() {
        if !c.is_ascii() {
            return format!("invalid character: found `{c}` at {}", index + offset + 1);
        }
        if c == '-' {
            if hyphens < 4 {
                bounds[hyphens] = index;
            }
            hyphens += 1;
        } else if !c.is_ascii_hexdigit() {
            return format!("invalid character: found `{c}` at {}", index + offset + 1);
        }
    }
    if hyphens == 0 && simple {
        return format!(
            "invalid length: expected length 32 for simple format, found {}",
            raw.len()
        );
    }
    if hyphens != 4 {
        return format!("invalid group count: expected 5, found {}", hyphens + 1);
    }
    const STARTS: [usize; 5] = [0, 9, 14, 19, 24];
    const LENGTHS: [usize; 5] = [8, 4, 4, 4, 12];
    for i in 0..4 {
        if bounds[i] != STARTS[i + 1] - 1 {
            return format!(
                "invalid group length in group {i}: expected {}, found {}",
                LENGTHS[i],
                bounds[i].saturating_sub(STARTS[i])
            );
        }
    }
    format!(
        "invalid group length in group 4: expected 12, found {}",
        body.len().saturating_sub(STARTS[4])
    )
}

/// A str enum (by value).
pub fn enumeration<T>(
    errs: &mut Errors,
    loc: &[Value],
    v: &Value,
    parse: fn(&str) -> Option<T>,
    expected: String,
) -> Option<T> {
    if let Value::String(s) = v
        && let Some(t) = parse(s)
    {
        return Some(t);
    }
    errs.push(
        "enum",
        loc,
        format!("Input should be {expected}"),
        v.clone(),
        Some(json!({"expected": expected})),
    );
    None
}

pub fn ge(errs: &mut Errors, loc: &[Value], value: i64, bound: i64, input: &Value) -> bool {
    if value < bound {
        errs.push(
            "greater_than_equal",
            loc,
            format!("Input should be greater than or equal to {bound}"),
            input.clone(),
            Some(json!({"ge": bound})),
        );
        return false;
    }
    true
}

pub fn le(errs: &mut Errors, loc: &[Value], value: i64, bound: i64, input: &Value) -> bool {
    if value > bound {
        errs.push(
            "less_than_equal",
            loc,
            format!("Input should be less than or equal to {bound}"),
            input.clone(),
            Some(json!({"le": bound})),
        );
        return false;
    }
    true
}

/// An `HttpUrl` with a length cap; the URL as pydantic normalizes it.
pub fn http_url(errs: &mut Errors, loc: &[Value], v: &Value, max: usize) -> Option<String> {
    let Value::String(s) = v else {
        errs.push("url_type", loc, "URL input should be a string or URL", v.clone(), None);
        return None;
    };
    if pyfmt::char_len(s) > max {
        errs.push(
            "url_too_long",
            loc,
            format!("URL should have at most {max} {}", char_word(max)),
            v.clone(),
            Some(json!({"max_length": max})),
        );
        return None;
    }
    match url::Url::parse(s) {
        Err(e) => {
            let detail = e.to_string();
            errs.push(
                "url_parsing",
                loc,
                format!("Input should be a valid URL, {detail}"),
                v.clone(),
                Some(json!({"error": detail})),
            );
            None
        }
        Ok(u) if u.scheme() != "http" && u.scheme() != "https" => {
            errs.push(
                "url_scheme",
                loc,
                "URL scheme should be 'http' or 'https'",
                v.clone(),
                Some(json!({"expected_schemes": "'http' or 'https'"})),
            );
            None
        }
        Ok(u) => Some(u.to_string()),
    }
}

// --- query / path ------------------------------------------------------------------------

/// Query parameters; a repeated key keeps its last value.
pub struct QueryParams(HashMap<String, String>);

impl QueryParams {
    pub fn parse(raw: Option<&str>) -> Self {
        let mut map = HashMap::new();
        if let Some(q) = raw {
            for (k, v) in url::form_urlencoded::parse(q.as_bytes()) {
                map.insert(k.into_owned(), v.into_owned());
            }
        }
        Self(map)
    }

    pub fn get(&self, name: &str) -> Option<Value> {
        self.0.get(name).map(|s| Value::String(s.clone()))
    }

    pub fn int(&self, errs: &mut Errors, name: &str, default: i64, min: Option<i64>, max: Option<i64>) -> i64 {
        let Some(raw) = self.get(name) else {
            return default;
        };
        let l = loc(&["query", name]);
        let Some(v) = integer(errs, &l, &raw) else {
            return default;
        };
        if let Some(m) = min
            && !ge(errs, &l, v, m, &raw)
        {
            return default;
        }
        if let Some(m) = max
            && !le(errs, &l, v, m, &raw)
        {
            return default;
        }
        v
    }

    pub fn opt_enum<T>(
        &self,
        errs: &mut Errors,
        name: &str,
        parse: fn(&str) -> Option<T>,
        expected: String,
    ) -> Option<T> {
        let raw = self.get(name)?;
        enumeration(errs, &loc(&["query", name]), &raw, parse, expected)
    }

    pub fn opt_str(&self, errs: &mut Errors, name: &str, max: usize) -> Option<String> {
        let raw = self.get(name)?;
        string(errs, &loc(&["query", name]), &raw, None, Some(max))
    }

    pub fn bool(&self, errs: &mut Errors, name: &str, default: bool) -> bool {
        match self.get(name) {
            None => default,
            Some(raw) => boolean(errs, &loc(&["query", name]), &raw).unwrap_or(default),
        }
    }

    pub fn required_uuid(&self, errs: &mut Errors, name: &str) -> Option<Uuid> {
        match self.get(name) {
            None => {
                errs.push("missing", &loc(&["query", name]), "Field required", Value::Null, None);
                None
            }
            Some(raw) => uuid(errs, &loc(&["query", name]), &raw),
        }
    }
}

pub fn path_uuid(errs: &mut Errors, name: &str, raw: &str) -> Option<Uuid> {
    uuid(errs, &loc(&["path", name]), &Value::String(raw.to_string()))
}

pub fn path_int(errs: &mut Errors, name: &str, raw: &str) -> Option<i64> {
    integer(errs, &loc(&["path", name]), &Value::String(raw.to_string()))
}

// --- body ------------------------------------------------------------------------------------

/// The request body as FastAPI read it: `None` when empty.
pub fn parse_body(_headers: &HeaderMap, bytes: &[u8]) -> Result<Option<Value>, ApiError> {
    if bytes.is_empty() {
        return Ok(None);
    }
    match serde_json::from_slice::<Value>(bytes) {
        Ok(v) => Ok(Some(v)),
        Err(e) => {
            let text = String::from_utf8_lossy(bytes);
            let mut pos = char_offset(&text, e.line(), e.column());
            let message = python_json_message(&e);
            if e.to_string().starts_with("expected ident") {
                // A bad literal: Python points at the token's first character.
                let chars: Vec<char> = text.chars().collect();
                while pos > 0 && chars.get(pos - 1).is_some_and(|c| c.is_alphanumeric()) {
                    pos -= 1;
                }
            }
            let mut errs = Errors::default();
            errs.push(
                "json_invalid",
                &[json!("body"), json!(pos)],
                "JSON decode error",
                json!({}),
                Some(json!({"error": message})),
            );
            Err(ApiError::Validation(errs.0))
        }
    }
}

fn char_offset(text: &str, line: usize, column: usize) -> usize {
    let mut offset = 0;
    for (i, l) in text.split('\n').enumerate() {
        if i + 1 == line {
            return offset + column.saturating_sub(1).min(pyfmt::char_len(l));
        }
        offset += pyfmt::char_len(l) + 1;
    }
    offset
}

/// The `json` module's error message for the same kind of failure.
fn python_json_message(e: &serde_json::Error) -> &'static str {
    let m = e.to_string();
    if m.starts_with("trailing characters") {
        "Extra data"
    } else if m.starts_with("key must be a string") {
        "Expecting property name enclosed in double quotes"
    } else if m.starts_with("expected `:`") {
        "Expecting ':' delimiter"
    } else if m.starts_with("expected `,`") {
        "Expecting ',' delimiter"
    } else if m.starts_with("EOF while parsing a string") {
        "Unterminated string starting at"
    } else if m.starts_with("control character") {
        "Invalid control character at"
    } else if m.starts_with("invalid escape") {
        "Invalid \\escape"
    } else {
        "Expecting value"
    }
}

/// The fields of a body FastAPI embeds (several `Body` parameters, or one
/// with `embed=True`): each read from the top-level object, a missing one
/// (or a body that is not an object) reported with input `null`.
pub struct EmbeddedBody<'a>(Option<&'a Map<String, Value>>);

impl<'a> EmbeddedBody<'a> {
    pub fn new(body: &'a Option<Value>) -> Self {
        Self(body.as_ref().and_then(Value::as_object))
    }

    pub fn field(&self, errs: &mut Errors, name: &str) -> Option<&'a Value> {
        // FastAPI reads embedded fields with `.get()`: an explicit null is
        // as missing as an absent key.
        match self.0.and_then(|m| m.get(name)).filter(|v| !v.is_null()) {
            Some(v) => Some(v),
            None => {
                errs.push("missing", &loc(&["body", name]), "Field required", Value::Null, None);
                None
            }
        }
    }
}

/// A single model body: the object to read fields from, or the error for a
/// missing or non-object body.
pub fn model_body<'a>(errs: &mut Errors, body: &'a Option<Value>) -> Option<&'a Map<String, Value>> {
    match body {
        None => {
            errs.push("missing", &loc(&["body"]), "Field required", Value::Null, None);
            None
        }
        Some(Value::Object(m)) => Some(m),
        Some(other) => {
            errs.push(
                "model_attributes_type",
                &loc(&["body"]),
                "Input should be a valid dictionary or object to extract fields from",
                other.clone(),
                None,
            );
            None
        }
    }
}

/// `extra="forbid"`: every key outside `allowed` is an error.
pub fn forbid_extra(errs: &mut Errors, base: &[Value], obj: &Map<String, Value>, allowed: &[&str]) {
    for (k, v) in obj {
        if !allowed.contains(&k.as_str()) {
            errs.push(
                "extra_forbidden",
                &loc_with(base, k),
                "Extra inputs are not permitted",
                v.clone(),
                None,
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn uuid_messages_match_pydantic() {
        let corpus: Vec<Value> =
            serde_json::from_str(include_str!("../../testdata/pydantic_uuid_corpus.json")).unwrap();
        for case in corpus {
            let input = case["in"].as_str().unwrap();
            let mut errs = Errors::default();
            let got = uuid(&mut errs, &loc(&["body", "u"]), &json!(input));
            if let Some(ok) = case.get("ok") {
                assert_eq!(got.map(|u| u.to_string()).as_deref(), ok.as_str(), "{input}");
            } else {
                assert_eq!(errs.0[0]["msg"], case["msg"], "{input}");
            }
        }
    }

    #[test]
    fn string_bounds() {
        let mut errs = Errors::default();
        assert!(string(&mut errs, &loc(&["body", "q"]), &json!(""), Some(1), None).is_none());
        assert_eq!(
            Value::Array(errs.0),
            json!([{"type":"string_too_short","loc":["body","q"],"msg":"String should have at least 1 character","input":"","ctx":{"min_length":1}}])
        );
    }

    #[test]
    fn json_decode_error_shape() {
        let err = parse_body(&HeaderMap::new(), b"not json").unwrap_err();
        let ApiError::Validation(v) = err else { panic!() };
        assert_eq!(
            Value::Array(v),
            json!([{"type":"json_invalid","loc":["body",0],"msg":"JSON decode error","input":{},"ctx":{"error":"Expecting value"}}])
        );
    }
}
