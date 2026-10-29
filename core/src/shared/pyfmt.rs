// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Python text semantics the core depends on.
//!
//! Prompts, tool results and log lines were shaped by Python's own
//! formatting (`repr`, `json.dumps`, `str.splitlines`, ...). Agents read
//! them and tests pin them, so they are reproduced here rather than
//! approximated with the nearest Rust idiom.

use serde_json::Value;

// --- whitespace / lines -------------------------------------------------

/// `str.isspace` for one character.
pub fn is_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// `str.strip()`.
pub fn strip(s: &str) -> &str {
    s.trim_matches(is_space)
}

/// `str.lstrip()`.
pub fn lstrip(s: &str) -> &str {
    s.trim_start_matches(is_space)
}

/// `str.rstrip()`.
pub fn rstrip(s: &str) -> &str {
    s.trim_end_matches(is_space)
}

fn is_line_break(c: char) -> bool {
    matches!(
        c,
        '\n' | '\r' | '\u{0b}' | '\u{0c}' | '\u{1c}' | '\u{1d}' | '\u{1e}' | '\u{85}' | '\u{2028}' | '\u{2029}'
    )
}

/// `str.splitlines()` (without `keepends`).
pub fn splitlines(s: &str) -> Vec<&str> {
    let mut lines = Vec::new();
    let mut start = 0;
    let mut chars = s.char_indices().peekable();
    while let Some((i, c)) = chars.next() {
        if is_line_break(c) {
            lines.push(&s[start..i]);
            let mut end = i + c.len_utf8();
            if c == '\r'
                && let Some(&(j, '\n')) = chars.peek()
            {
                chars.next();
                end = j + 1;
            }
            start = end;
        }
    }
    if start < s.len() {
        lines.push(&s[start..]);
    }
    lines
}

/// Text-mode read: universal newlines turn `\r\n` and `\r` into `\n`.
pub fn universal_newlines(s: &str) -> String {
    if !s.contains('\r') {
        return s.to_string();
    }
    s.replace("\r\n", "\n").replace('\r', "\n")
}

/// `s[:n]` on a str: the first `n` code points.
pub fn take_chars(s: &str, n: usize) -> &str {
    match s.char_indices().nth(n) {
        Some((i, _)) => &s[..i],
        None => s,
    }
}

/// `s[n:]` on a str.
pub fn skip_chars(s: &str, n: usize) -> &str {
    match s.char_indices().nth(n) {
        Some((i, _)) => &s[i..],
        None => "",
    }
}

/// `len(s)` on a str.
pub fn char_len(s: &str) -> usize {
    s.chars().count()
}

/// `str.casefold()`; full folding for the characters where it differs
/// from `lower()`.
pub fn casefold(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            'ß' | 'ẞ' => out.push_str("ss"),
            'ς' => out.push('σ'),
            'ſ' => out.push('s'),
            'ﬀ' => out.push_str("ff"),
            'ﬁ' => out.push_str("fi"),
            'ﬂ' => out.push_str("fl"),
            'ﬃ' => out.push_str("ffi"),
            'ﬄ' => out.push_str("ffl"),
            'ﬅ' | 'ﬆ' => out.push_str("st"),
            _ => out.extend(c.to_lowercase()),
        }
    }
    out
}

// --- repr ------------------------------------------------------------

/// `str.isprintable` for one character, minus the unassigned code points
/// (category Cn), which would need the full Unicode tables.
fn is_printable(c: char) -> bool {
    let cp = c as u32;
    if c == ' ' {
        return true;
    }
    // Cc
    if cp < 0x20 || (0x7f..0xa0).contains(&cp) {
        return false;
    }
    // Zs (other than space), Zl, Zp
    if matches!(
        cp,
        0xa0 | 0x1680 | 0x2000..=0x200a | 0x2028 | 0x2029 | 0x202f | 0x205f | 0x3000
    ) {
        return false;
    }
    // Cf
    if matches!(
        cp,
        0xad | 0x600..=0x605
            | 0x61c
            | 0x6dd
            | 0x70f
            | 0x890..=0x891
            | 0x8e2
            | 0x180e
            | 0x200b..=0x200f
            | 0x202a..=0x202e
            | 0x2060..=0x2064
            | 0x2066..=0x206f
            | 0xfeff
            | 0xfff9..=0xfffb
            | 0x110bd
            | 0x110cd
            | 0x13430..=0x1343f
            | 0x1bca0..=0x1bca3
            | 0x1d173..=0x1d17a
            | 0xe0001
            | 0xe0020..=0xe007f
    ) {
        return false;
    }
    // Co
    if matches!(cp, 0xe000..=0xf8ff | 0xf0000..=0xffffd | 0x100000..=0x10fffd) {
        return false;
    }
    // Noncharacters are Cn
    if (cp & 0xfffe) == 0xfffe || (0xfdd0..=0xfdef).contains(&cp) {
        return false;
    }
    true
}

/// `repr(s)` for a str.
pub fn repr_str(s: &str) -> String {
    let quote = if s.contains('\'') && !s.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::with_capacity(s.len() + 2);
    out.push(quote);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c if is_printable(c) => out.push(c),
            c => {
                let cp = c as u32;
                if cp < 0x100 {
                    out.push_str(&format!("\\x{cp:02x}"));
                } else if cp < 0x10000 {
                    out.push_str(&format!("\\u{cp:04x}"));
                } else {
                    out.push_str(&format!("\\U{cp:08x}"));
                }
            }
        }
    }
    out.push(quote);
    out
}

/// `repr(float)`: the shortest round-tripping digits, laid out the way
/// CPython's `float_repr_style == 'short'` does.
pub fn repr_float(x: f64) -> String {
    if x.is_nan() {
        return "nan".to_string();
    }
    if x.is_infinite() {
        return if x > 0.0 { "inf".into() } else { "-inf".into() };
    }
    if x == 0.0 {
        return if x.is_sign_negative() {
            "-0.0".into()
        } else {
            "0.0".into()
        };
    }
    // Rust's `{:e}` gives the shortest round-trip digits as d.ddddde±x.
    let sci = format!("{:e}", x);
    let (mantissa, exp) = sci.split_once('e').expect("exponent");
    let exp: i32 = exp.parse().expect("exponent value");
    let negative = mantissa.starts_with('-');
    let digits: String = mantissa.chars().filter(|c| c.is_ascii_digit()).collect();
    let mut out = String::new();
    if negative {
        out.push('-');
    }
    // CPython switches to exponent notation when decpt <= -4 or decpt > 16,
    // where decpt = exp + 1.
    let decpt = exp + 1;
    if decpt <= -4 || decpt > 16 {
        out.push_str(&digits[..1]);
        if digits.len() > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        out.push('e');
        out.push(if exp < 0 { '-' } else { '+' });
        out.push_str(&format!("{:02}", exp.abs()));
    } else if decpt <= 0 {
        out.push_str("0.");
        for _ in 0..(-decpt) {
            out.push('0');
        }
        out.push_str(&digits);
    } else {
        let decpt = decpt as usize;
        if digits.len() <= decpt {
            out.push_str(&digits);
            for _ in 0..(decpt - digits.len()) {
                out.push('0');
            }
            out.push_str(".0");
        } else {
            out.push_str(&digits[..decpt]);
            out.push('.');
            out.push_str(&digits[decpt..]);
        }
    }
    out
}

fn repr_number(n: &serde_json::Number) -> String {
    if n.is_f64() {
        repr_float(n.as_f64().unwrap_or(0.0))
    } else {
        n.to_string()
    }
}

/// `repr()` of the Python value a JSON document decodes to.
pub fn repr_value(v: &Value) -> String {
    match v {
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::Number(n) => repr_number(n),
        Value::String(s) => repr_str(s),
        Value::Array(items) => {
            let inner: Vec<String> = items.iter().map(repr_value).collect();
            format!("[{}]", inner.join(", "))
        }
        Value::Object(map) => {
            let inner: Vec<String> = map
                .iter()
                .map(|(k, v)| format!("{}: {}", repr_str(k), repr_value(v)))
                .collect();
            format!("{{{}}}", inner.join(", "))
        }
    }
}

/// `str(v)`: like repr except a top-level str is itself.
pub fn str_value(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        other => repr_value(other),
    }
}

/// `repr(list_of_str)`.
pub fn repr_str_list<S: AsRef<str>>(items: &[S]) -> String {
    let inner: Vec<String> = items.iter().map(|s| repr_str(s.as_ref())).collect();
    format!("[{}]", inner.join(", "))
}

/// `repr(list_of_list_of_str)`.
pub fn repr_str_list_list<S: AsRef<str>>(groups: &[Vec<S>]) -> String {
    let inner: Vec<String> = groups.iter().map(|g| repr_str_list(g)).collect();
    format!("[{}]", inner.join(", "))
}

// --- json.dumps --------------------------------------------------------

fn dump_str(s: &str, ensure_ascii: bool, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c if ensure_ascii && (c as u32) > 0x7e => {
                let mut buf = [0u16; 2];
                for unit in c.encode_utf16(&mut buf) {
                    out.push_str(&format!("\\u{:04x}", unit));
                }
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

fn dump_value(v: &Value, ensure_ascii: bool, out: &mut String) {
    match v {
        Value::Null => out.push_str("null"),
        Value::Bool(true) => out.push_str("true"),
        Value::Bool(false) => out.push_str("false"),
        Value::Number(n) => out.push_str(&repr_number(n)),
        Value::String(s) => dump_str(s, ensure_ascii, out),
        Value::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                dump_value(item, ensure_ascii, out);
            }
            out.push(']');
        }
        Value::Object(map) => {
            out.push('{');
            for (i, (k, item)) in map.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                dump_str(k, ensure_ascii, out);
                out.push_str(": ");
                dump_value(item, ensure_ascii, out);
            }
            out.push('}');
        }
    }
}

/// `json.dumps(v)`: default separators and `ensure_ascii=True`.
pub fn json_dumps(v: &Value) -> String {
    let mut out = String::new();
    dump_value(v, true, &mut out);
    out
}

/// `json.dumps(v, ensure_ascii=False)`.
pub fn json_dumps_unicode(v: &Value) -> String {
    let mut out = String::new();
    dump_value(v, false, &mut out);
    out
}

/// `json.dumps(v, sort_keys=True)`.
pub fn json_dumps_sorted(v: &Value) -> String {
    json_dumps(&sort_keys(v))
}

fn sort_keys(v: &Value) -> Value {
    match v {
        Value::Array(items) => Value::Array(items.iter().map(sort_keys).collect()),
        Value::Object(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            let mut sorted = serde_json::Map::new();
            for k in keys {
                sorted.insert(k.clone(), sort_keys(&map[k]));
            }
            Value::Object(sorted)
        }
        other => other.clone(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn splitlines_matches_python() {
        assert_eq!(splitlines("a\nb\r\nc\rd"), vec!["a", "b", "c", "d"]);
        assert_eq!(splitlines("a\n"), vec!["a"]);
        assert_eq!(splitlines("\n\n"), vec!["", ""]);
        assert_eq!(splitlines(""), Vec::<&str>::new());
        assert_eq!(splitlines("a\u{2028}b\x0bc"), vec!["a", "b", "c"]);
    }

    #[test]
    fn repr_str_quotes() {
        assert_eq!(repr_str("abc"), "'abc'");
        assert_eq!(repr_str("it's"), "\"it's\"");
        assert_eq!(repr_str("a'b\"c"), "'a\\'b\"c'");
        assert_eq!(repr_str("tab\there\n"), "'tab\\there\\n'");
        assert_eq!(repr_str("\u{a0}é"), "'\\xa0é'");
        assert_eq!(repr_str("\u{7}"), "'\\x07'");
    }

    #[test]
    fn repr_float_layout() {
        assert_eq!(repr_float(1.0), "1.0");
        assert_eq!(repr_float(0.1), "0.1");
        assert_eq!(repr_float(1e16), "1e+16");
        assert_eq!(repr_float(1e15), "1000000000000000.0");
        assert_eq!(repr_float(0.0001), "0.0001");
        assert_eq!(repr_float(0.00001), "1e-05");
        assert_eq!(repr_float(-2.5), "-2.5");
        assert_eq!(repr_float(123456.789), "123456.789");
        assert_eq!(repr_float(1.5e-7), "1.5e-07");
        assert_eq!(repr_float(1.2345e20), "1.2345e+20");
    }

    #[test]
    fn json_dumps_python_style() {
        let v = json!({"a": [1, 2.0, "é"], "b": null, "c": true});
        assert_eq!(json_dumps(&v), r#"{"a": [1, 2.0, "\u00e9"], "b": null, "c": true}"#);
        assert_eq!(json_dumps_unicode(&v), r#"{"a": [1, 2.0, "é"], "b": null, "c": true}"#);
        assert_eq!(json_dumps(&json!("😀")), r#""\ud83d\ude00""#);
    }

    #[test]
    fn repr_value_python_style() {
        let v = json!({"a": [1, "x"], "b": null, "c": false});
        assert_eq!(repr_value(&v), "{'a': [1, 'x'], 'b': None, 'c': False}");
        assert_eq!(repr_str_list(&["a", "b"]), "['a', 'b']");
    }

    #[test]
    fn strip_uses_python_whitespace() {
        assert_eq!(strip("\u{1c} x \u{a0}"), "x");
    }
}
