// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Port of `json.loads(deepdiff.DeepDiff(t1, t2, verbose_level=2).to_json())`
//! (deepdiff 9.1.0, default options) for JSON values.
//!
//! It reproduces the report categories, paths, values and key order, including
//! deepdiff's quirks: dict keys starting with `__` are ignored, dicts sharing
//! fewer than 33% of their keys are reported as one whole-value change, lists of
//! scalars are diffed with a port of `difflib.SequenceMatcher` (where `1`, `1.0`
//! and `true` compare equal), and an item removed and added at the same index
//! becomes a `values_changed`.

use std::collections::{HashMap, HashSet};
use std::hash::Hash;

use serde_json::{Map, Value};

/// Returns exactly what `json.loads(DeepDiff(t1, t2, verbose_level=2).to_json())`
/// returns; an empty object when there is no difference.
pub fn deep_diff(t1: &Value, t2: &Value) -> Value {
    let mut reports = Vec::new();
    diff(t1, t2, "root", "root", &mut reports);
    render(reports)
}

/// deepdiff's `threshold_to_diff_deeper` default.
const THRESHOLD_TO_DIFF_DEEPER: f64 = 0.33;

#[derive(Clone, Copy, PartialEq, Eq)]
enum Kind {
    TypeChanges,
    DictionaryItemAdded,
    DictionaryItemRemoved,
    ValuesChanged,
    IterableItemAdded,
    IterableItemRemoved,
    IterableItemMoved,
}

impl Kind {
    /// Output order of `TextResult`.
    const ORDER: [Kind; 7] = [
        Kind::TypeChanges,
        Kind::DictionaryItemAdded,
        Kind::DictionaryItemRemoved,
        Kind::ValuesChanged,
        Kind::IterableItemAdded,
        Kind::IterableItemRemoved,
        Kind::IterableItemMoved,
    ];

    fn name(self) -> &'static str {
        match self {
            Kind::TypeChanges => "type_changes",
            Kind::DictionaryItemAdded => "dictionary_item_added",
            Kind::DictionaryItemRemoved => "dictionary_item_removed",
            Kind::ValuesChanged => "values_changed",
            Kind::IterableItemAdded => "iterable_item_added",
            Kind::IterableItemRemoved => "iterable_item_removed",
            Kind::IterableItemMoved => "iterable_item_moved",
        }
    }
}

/// One reported `DiffLevel`: `path` follows t1's side, `new_path` t2's side.
struct Report<'a> {
    kind: Kind,
    path: String,
    new_path: String,
    t1: Option<&'a Value>,
    t2: Option<&'a Value>,
    diff: Option<String>,
}

impl<'a> Report<'a> {
    fn new(kind: Kind, path: String, new_path: String, t1: Option<&'a Value>, t2: Option<&'a Value>) -> Self {
        Report {
            kind,
            path,
            new_path,
            t1,
            t2,
            diff: None,
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum PyType {
    NoneType,
    Bool,
    Int,
    Float,
    Str,
    Dict,
    List,
}

impl PyType {
    fn of(v: &Value) -> Self {
        match v {
            Value::Null => PyType::NoneType,
            Value::Bool(_) => PyType::Bool,
            Value::Number(n) if n.is_f64() => PyType::Float,
            Value::Number(_) => PyType::Int,
            Value::String(_) => PyType::Str,
            Value::Object(_) => PyType::Dict,
            Value::Array(_) => PyType::List,
        }
    }

    fn name(self) -> &'static str {
        match self {
            PyType::NoneType => "NoneType",
            PyType::Bool => "bool",
            PyType::Int => "int",
            PyType::Float => "float",
            PyType::Str => "str",
            PyType::Dict => "dict",
            PyType::List => "list",
        }
    }
}

/// A scalar with Python's `==`/`hash` semantics, where `True == 1 == 1.0`.
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
enum Scalar<'a> {
    None,
    Int(i128),
    Float(u64),
    Str(&'a str),
}

impl<'a> Scalar<'a> {
    fn of(v: &'a Value) -> Option<Self> {
        Some(match v {
            Value::Null => Scalar::None,
            Value::Bool(b) => Scalar::Int(i128::from(*b)),
            Value::Number(n) => {
                if let Some(i) = n.as_i64() {
                    Scalar::Int(i128::from(i))
                } else if let Some(u) = n.as_u64() {
                    Scalar::Int(i128::from(u))
                } else {
                    let f = n.as_f64().unwrap_or(f64::NAN);
                    // Integral floats equal (and hash like) the int of the same value.
                    if f.fract() == 0.0 && f.abs() < 1.7e38 {
                        Scalar::Int(f as i128)
                    } else {
                        Scalar::Float(f.to_bits())
                    }
                }
            }
            Value::String(s) => Scalar::Str(s),
            Value::Array(_) | Value::Object(_) => return None,
        })
    }
}

fn index_path(base: &str, index: usize) -> String {
    format!("{base}[{index}]")
}

/// `DictRelationship` param repr (`stringify_element` with quote_str `'{}'`).
fn key_path(base: &str, key: &str) -> String {
    if key.contains('\'') {
        format!("{base}[\"{key}\"]")
    } else {
        format!("{base}['{key}']")
    }
}

/// `DeepDiff._diff`.
fn diff<'a>(t1: &'a Value, t2: &'a Value, path: &str, new_path: &str, out: &mut Vec<Report<'a>>) {
    let report = |kind| Report::new(kind, path.to_owned(), new_path.to_owned(), Some(t1), Some(t2));
    let (ty1, ty2) = (PyType::of(t1), PyType::of(t2));
    if ty1 != ty2 {
        out.push(report(Kind::TypeChanges));
        return;
    }
    match (t1, t2) {
        (Value::Bool(a), Value::Bool(b)) if a != b => out.push(report(Kind::ValuesChanged)),
        (Value::Number(_), Value::Number(_)) if Scalar::of(t1) != Scalar::of(t2) => {
            out.push(report(Kind::ValuesChanged));
        }
        (Value::String(a), Value::String(b)) if a != b => {
            let mut r = report(Kind::ValuesChanged);
            if a.contains('\n') || b.contains('\n') {
                let lines = unified_diff(&splitlines(a), &splitlines(b));
                if !lines.is_empty() {
                    r.diff = Some(lines.join("\n"));
                }
            }
            out.push(r);
        }
        (Value::Object(a), Value::Object(b)) => diff_dict(t1, t2, a, b, path, new_path, out),
        (Value::Array(a), Value::Array(b)) => diff_list(a, b, path, new_path, out),
        _ => {}
    }
}

/// `DeepDiff._diff_dict` (`ignore_private_variables=True`).
fn diff_dict<'a>(
    t1: &'a Value,
    t2: &'a Value,
    a: &'a Map<String, Value>,
    b: &'a Map<String, Value>,
    path: &str,
    new_path: &str,
    out: &mut Vec<Report<'a>>,
) {
    let visible = |k: &&String| !k.starts_with("__");
    let t1_keys: Vec<&String> = a.keys().filter(visible).collect();
    let t2_keys: Vec<&String> = b.keys().filter(visible).collect();
    let t1_set: HashSet<&String> = t1_keys.iter().copied().collect();
    let t2_set: HashSet<&String> = t2_keys.iter().copied().collect();
    let intersect: Vec<&String> = t2_keys.iter().copied().filter(|k| t1_set.contains(k)).collect();
    let added: Vec<&String> = t2_keys.iter().copied().filter(|k| !t1_set.contains(k)).collect();
    let removed: Vec<&String> = t1_keys.iter().copied().filter(|k| !t2_set.contains(k)).collect();

    let union_len = t1_keys.len() + added.len();
    if union_len > 1 && (intersect.len() as f64) / (union_len as f64) < THRESHOLD_TO_DIFF_DEEPER {
        out.push(Report::new(
            Kind::ValuesChanged,
            path.to_owned(),
            new_path.to_owned(),
            Some(t1),
            Some(t2),
        ));
        return;
    }
    for key in added {
        out.push(Report::new(
            Kind::DictionaryItemAdded,
            key_path(path, key),
            key_path(new_path, key),
            None,
            Some(&b[key.as_str()]),
        ));
    }
    for key in removed {
        out.push(Report::new(
            Kind::DictionaryItemRemoved,
            key_path(path, key),
            key_path(new_path, key),
            Some(&a[key.as_str()]),
            None,
        ));
    }
    for key in intersect {
        diff(
            &a[key.as_str()],
            &b[key.as_str()],
            &key_path(path, key),
            &key_path(new_path, key),
            out,
        );
    }
}

/// `DeepDiff._diff_iterable_in_order`.
fn diff_list<'a>(a: &'a [Value], b: &'a [Value], path: &str, new_path: &str, out: &mut Vec<Report<'a>>) {
    let keys_a: Option<Vec<Scalar<'a>>> = a.iter().map(Scalar::of).collect();
    let keys_b: Option<Vec<Scalar<'a>>> = b.iter().map(Scalar::of).collect();
    let (Some(keys_a), Some(keys_b)) = (keys_a, keys_b) else {
        diff_pairs(a, b, 0, 0, path, new_path, out);
        return;
    };

    let mut pass1 = Vec::new();
    let matcher = SequenceMatcher::new(&keys_a, &keys_b, false);
    for op in matcher.get_opcodes() {
        let (i1, i2, j1, j2) = (op.i1, op.i2, op.j1, op.j2);
        match op.tag {
            Tag::Equal => {}
            Tag::Replace => diff_pairs(&a[i1..i2], &b[j1..j2], i1, j1, path, new_path, &mut pass1),
            Tag::Delete => {
                for (i, x) in a.iter().enumerate().take(i2).skip(i1) {
                    pass1.push(Report::new(
                        Kind::IterableItemRemoved,
                        index_path(path, i),
                        index_path(new_path, i),
                        Some(x),
                        None,
                    ));
                }
            }
            Tag::Insert => {
                for (j, y) in b.iter().enumerate().take(j2).skip(j1) {
                    pass1.push(Report::new(
                        Kind::IterableItemAdded,
                        index_path(path, j),
                        index_path(new_path, j),
                        None,
                        Some(y),
                    ));
                }
            }
        }
    }
    // deepdiff keeps the plain index-by-index diff when it reports no more changes.
    if pass1.len() > 1 {
        let mut pass2 = Vec::new();
        diff_pairs(a, b, 0, 0, path, new_path, &mut pass2);
        if pass1.len() >= pass2.len() {
            pass1 = pass2;
        }
    }
    out.extend(pass1);
}

/// `DeepDiff._diff_by_forming_pairs_and_comparing_one_by_one` with the default
/// in-order pairing; `a`/`b` are slices starting at `a_off`/`b_off`.
fn diff_pairs<'a>(
    a: &'a [Value],
    b: &'a [Value],
    a_off: usize,
    b_off: usize,
    path: &str,
    new_path: &str,
    out: &mut Vec<Report<'a>>,
) {
    for k in 0..a.len().max(b.len()) {
        let (i, j) = (k + a_off, k + b_off);
        match (a.get(k), b.get(k)) {
            (Some(x), None) => out.push(Report::new(
                Kind::IterableItemRemoved,
                index_path(path, i),
                index_path(new_path, i),
                Some(x),
                None,
            )),
            (None, Some(y)) => out.push(Report::new(
                Kind::IterableItemAdded,
                index_path(path, j),
                index_path(new_path, j),
                None,
                Some(y),
            )),
            (Some(x), Some(y)) => {
                // Offsets only differ inside a difflib replace block, where items are scalars.
                if i != j && Scalar::of(x).is_some() && Scalar::of(x) == Scalar::of(y) {
                    out.push(Report::new(
                        Kind::IterableItemMoved,
                        index_path(path, i),
                        index_path(new_path, j),
                        Some(x),
                        Some(y),
                    ));
                    continue;
                }
                diff(x, y, &index_path(path, i), &index_path(new_path, j), out);
            }
            (None, None) => unreachable!(),
        }
    }
}

/// `TreeResult.mutual_add_removes_to_become_value_changes` followed by `TextResult`.
fn render(mut reports: Vec<Report<'_>>) -> Value {
    let mut added: HashMap<String, usize> = HashMap::new();
    let mut removed: Vec<(String, usize)> = Vec::new();
    let mut removed_pos: HashMap<String, usize> = HashMap::new();
    for (idx, r) in reports.iter().enumerate() {
        match r.kind {
            Kind::IterableItemAdded => {
                added.insert(r.path.clone(), idx);
            }
            Kind::IterableItemRemoved => match removed_pos.get(&r.path) {
                Some(&pos) => removed[pos].1 = idx,
                None => {
                    removed_pos.insert(r.path.clone(), removed.len());
                    removed.push((r.path.clone(), idx));
                }
            },
            _ => {}
        }
    }
    // Python iterates these in `set` order, which depends on the per-process string
    // hash seed; removal order is used as the deterministic equivalent.
    let mut dropped = vec![false; reports.len()];
    let mut merged = Vec::new();
    for (p, ri) in &removed {
        if let Some(&ai) = added.get(p) {
            dropped[*ri] = true;
            dropped[ai] = true;
            let (before, after) = (&reports[*ri], &reports[ai]);
            merged.push(Report::new(
                Kind::ValuesChanged,
                before.path.clone(),
                before.new_path.clone(),
                before.t1,
                after.t2,
            ));
        }
    }
    let mut kept: Vec<Report<'_>> = Vec::with_capacity(reports.len());
    for (r, drop) in reports.drain(..).zip(dropped) {
        if !drop {
            kept.push(r);
        }
    }
    kept.extend(merged);

    let mut result = Map::new();
    for kind in Kind::ORDER {
        let mut section = Map::new();
        for r in kept.iter().filter(|r| r.kind == kind) {
            let entry = match kind {
                Kind::TypeChanges => {
                    let (t1, t2) = (r.t1.unwrap_or(&Value::Null), r.t2.unwrap_or(&Value::Null));
                    let mut m = Map::new();
                    m.insert("old_type".into(), PyType::of(t1).name().into());
                    m.insert("new_type".into(), PyType::of(t2).name().into());
                    if r.path != r.new_path {
                        m.insert("new_path".into(), r.new_path.clone().into());
                    }
                    m.insert("old_value".into(), t1.clone());
                    m.insert("new_value".into(), t2.clone());
                    Value::Object(m)
                }
                Kind::ValuesChanged => {
                    let mut m = Map::new();
                    m.insert("new_value".into(), r.t2.cloned().unwrap_or(Value::Null));
                    m.insert("old_value".into(), r.t1.cloned().unwrap_or(Value::Null));
                    if r.path != r.new_path {
                        m.insert("new_path".into(), r.new_path.clone().into());
                    }
                    if let Some(d) = &r.diff {
                        m.insert("diff".into(), d.clone().into());
                    }
                    Value::Object(m)
                }
                Kind::IterableItemMoved => {
                    let mut m = Map::new();
                    m.insert("new_path".into(), r.new_path.clone().into());
                    m.insert("value".into(), r.t2.cloned().unwrap_or(Value::Null));
                    Value::Object(m)
                }
                _ => r.t2.or(r.t1).cloned().unwrap_or(Value::Null),
            };
            section.insert(r.path.clone(), entry);
        }
        if !section.is_empty() {
            result.insert(kind.name().into(), Value::Object(section));
        }
    }
    Value::Object(result)
}

/// `str.splitlines()`.
fn splitlines(s: &str) -> Vec<&str> {
    let mut lines = Vec::new();
    let mut start = 0;
    let mut chars = s.char_indices().peekable();
    while let Some((i, c)) = chars.next() {
        let end = match c {
            '\r' => match chars.peek() {
                Some(&(_, '\n')) => {
                    chars.next();
                    i + 2
                }
                _ => i + 1,
            },
            '\n' | '\x0b' | '\x0c' | '\x1c' | '\x1d' | '\x1e' | '\u{85}' | '\u{2028}' | '\u{2029}' => i + c.len_utf8(),
            _ => continue,
        };
        lines.push(&s[start..i]);
        start = end;
    }
    if start < s.len() {
        lines.push(&s[start..]);
    }
    lines
}

/// `difflib.unified_diff(a, b, lineterm='')` with default file names and `n=3`.
fn unified_diff(a: &[&str], b: &[&str]) -> Vec<String> {
    fn range(start: usize, stop: usize) -> String {
        let length = stop - start;
        match length {
            1 => format!("{}", start + 1),
            0 => format!("{start},0"),
            _ => format!("{},{}", start + 1, length),
        }
    }
    let mut out = Vec::new();
    let matcher = SequenceMatcher::new(a, b, true);
    for group in matcher.get_grouped_opcodes(3) {
        if out.is_empty() {
            out.push("--- ".to_owned());
            out.push("+++ ".to_owned());
        }
        let (first, last) = (&group[0], &group[group.len() - 1]);
        out.push(format!(
            "@@ -{} +{} @@",
            range(first.i1, last.i2),
            range(first.j1, last.j2)
        ));
        for op in &group {
            if op.tag == Tag::Equal {
                out.extend(a[op.i1..op.i2].iter().map(|l| format!(" {l}")));
                continue;
            }
            if matches!(op.tag, Tag::Replace | Tag::Delete) {
                out.extend(a[op.i1..op.i2].iter().map(|l| format!("-{l}")));
            }
            if matches!(op.tag, Tag::Replace | Tag::Insert) {
                out.extend(b[op.j1..op.j2].iter().map(|l| format!("+{l}")));
            }
        }
    }
    out
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Tag {
    Replace,
    Delete,
    Insert,
    Equal,
}

#[derive(Clone, Copy, Debug)]
struct Opcode {
    tag: Tag,
    i1: usize,
    i2: usize,
    j1: usize,
    j2: usize,
}

/// `difflib.SequenceMatcher` with `isjunk=None`.
struct SequenceMatcher<'s, T> {
    a: &'s [T],
    b: &'s [T],
    b2j: HashMap<&'s T, Vec<usize>>,
}

impl<'s, T: Eq + Hash> SequenceMatcher<'s, T> {
    fn new(a: &'s [T], b: &'s [T], autojunk: bool) -> Self {
        let mut b2j: HashMap<&T, Vec<usize>> = HashMap::new();
        for (i, elt) in b.iter().enumerate() {
            b2j.entry(elt).or_default().push(i);
        }
        if autojunk && b.len() >= 200 {
            let ntest = b.len() / 100 + 1;
            b2j.retain(|_, idxs| idxs.len() <= ntest);
        }
        SequenceMatcher { a, b, b2j }
    }

    fn find_longest_match(&self, alo: usize, ahi: usize, blo: usize, bhi: usize) -> (usize, usize, usize) {
        let (a, b) = (self.a, self.b);
        let (mut besti, mut bestj, mut bestsize) = (alo, blo, 0);
        let mut j2len: HashMap<usize, usize> = HashMap::new();
        for (i, elt) in a.iter().enumerate().take(ahi).skip(alo) {
            let mut newj2len = HashMap::new();
            if let Some(js) = self.b2j.get(elt) {
                for &j in js {
                    if j < blo {
                        continue;
                    }
                    if j >= bhi {
                        break;
                    }
                    let k = if j > 0 {
                        j2len.get(&(j - 1)).copied().unwrap_or(0)
                    } else {
                        0
                    } + 1;
                    newj2len.insert(j, k);
                    if k > bestsize {
                        (besti, bestj, bestsize) = (i + 1 - k, j + 1 - k, k);
                    }
                }
            }
            j2len = newj2len;
        }
        // There is no junk, so only the non-junk extension loops can apply; they
        // still extend over "popular" elements dropped from b2j by autojunk.
        while besti > alo && bestj > blo && a[besti - 1] == b[bestj - 1] {
            (besti, bestj, bestsize) = (besti - 1, bestj - 1, bestsize + 1);
        }
        while besti + bestsize < ahi && bestj + bestsize < bhi && a[besti + bestsize] == b[bestj + bestsize] {
            bestsize += 1;
        }
        (besti, bestj, bestsize)
    }

    fn get_matching_blocks(&self) -> Vec<(usize, usize, usize)> {
        let (la, lb) = (self.a.len(), self.b.len());
        let mut queue = vec![(0, la, 0, lb)];
        let mut blocks = Vec::new();
        while let Some((alo, ahi, blo, bhi)) = queue.pop() {
            let (i, j, k) = self.find_longest_match(alo, ahi, blo, bhi);
            if k > 0 {
                blocks.push((i, j, k));
                if alo < i && blo < j {
                    queue.push((alo, i, blo, j));
                }
                if i + k < ahi && j + k < bhi {
                    queue.push((i + k, ahi, j + k, bhi));
                }
            }
        }
        blocks.sort_unstable();

        let (mut i1, mut j1, mut k1) = (0, 0, 0);
        let mut non_adjacent = Vec::new();
        for (i2, j2, k2) in blocks {
            if i1 + k1 == i2 && j1 + k1 == j2 {
                k1 += k2;
            } else {
                if k1 > 0 {
                    non_adjacent.push((i1, j1, k1));
                }
                (i1, j1, k1) = (i2, j2, k2);
            }
        }
        if k1 > 0 {
            non_adjacent.push((i1, j1, k1));
        }
        non_adjacent.push((la, lb, 0));
        non_adjacent
    }

    fn get_opcodes(&self) -> Vec<Opcode> {
        let (mut i, mut j) = (0, 0);
        let mut answer = Vec::new();
        for (ai, bj, size) in self.get_matching_blocks() {
            let tag = if i < ai && j < bj {
                Some(Tag::Replace)
            } else if i < ai {
                Some(Tag::Delete)
            } else if j < bj {
                Some(Tag::Insert)
            } else {
                None
            };
            if let Some(tag) = tag {
                answer.push(Opcode {
                    tag,
                    i1: i,
                    i2: ai,
                    j1: j,
                    j2: bj,
                });
            }
            (i, j) = (ai + size, bj + size);
            if size > 0 {
                answer.push(Opcode {
                    tag: Tag::Equal,
                    i1: ai,
                    i2: i,
                    j1: bj,
                    j2: j,
                });
            }
        }
        answer
    }

    fn get_grouped_opcodes(&self, n: usize) -> Vec<Vec<Opcode>> {
        let mut codes = self.get_opcodes();
        if codes.is_empty() {
            codes.push(Opcode {
                tag: Tag::Equal,
                i1: 0,
                i2: 1,
                j1: 0,
                j2: 1,
            });
        }
        if let Some(c) = codes.first_mut().filter(|c| c.tag == Tag::Equal) {
            c.i1 = c.i1.max(c.i2.saturating_sub(n));
            c.j1 = c.j1.max(c.j2.saturating_sub(n));
        }
        if let Some(c) = codes.last_mut().filter(|c| c.tag == Tag::Equal) {
            c.i2 = c.i2.min(c.i1 + n);
            c.j2 = c.j2.min(c.j1 + n);
        }
        let mut groups = Vec::new();
        let mut group = Vec::new();
        for mut c in codes {
            if c.tag == Tag::Equal && c.i2 - c.i1 > 2 * n {
                group.push(Opcode {
                    i2: c.i2.min(c.i1 + n),
                    j2: c.j2.min(c.j1 + n),
                    ..c
                });
                groups.push(std::mem::take(&mut group));
                c.i1 = c.i1.max(c.i2.saturating_sub(n));
                c.j1 = c.j1.max(c.j2.saturating_sub(n));
            }
            group.push(c);
        }
        if !group.is_empty() && !(group.len() == 1 && group[0].tag == Tag::Equal) {
            groups.push(group);
        }
        groups
    }
}

#[cfg(test)]
mod tests {
    use super::deep_diff;
    use serde_json::{Value, json};

    /// Compares serialized text so key order is checked too. Expected values were
    /// captured from deepdiff 9.1.0.
    fn check(t1: Value, t2: Value, expected: &str) {
        let expected: Value = serde_json::from_str(expected).unwrap();
        assert_eq!(deep_diff(&t1, &t2).to_string(), expected.to_string());
    }

    #[test]
    fn equal_values_give_empty_object() {
        check(json!({"a": 1, "b": [1, 2]}), json!({"a": 1, "b": [1, 2]}), "{}");
    }

    #[test]
    fn root_type_change() {
        check(
            json!(1),
            json!(null),
            r#"{"type_changes": {"root": {"old_type": "int", "new_type": "NoneType", "old_value": 1, "new_value": null}}}"#,
        );
    }

    #[test]
    fn dict_added_removed_and_nested_change() {
        check(
            json!({"id": "x", "tags": {"Name": "a", "env": "dev"}, "old": 1}),
            json!({"id": "x", "tags": {"Name": "b", "env": "dev"}, "new": 2}),
            r#"{"dictionary_item_added": {"root['new']": 2}, "dictionary_item_removed": {"root['old']": 1}, "values_changed": {"root['tags']['Name']": {"new_value": "b", "old_value": "a"}}}"#,
        );
    }

    #[test]
    fn dicts_with_few_shared_keys_change_as_a_whole() {
        check(
            json!({"a": 1, "b": 2}),
            json!({"c": 3}),
            r#"{"values_changed": {"root": {"new_value": {"c": 3}, "old_value": {"a": 1, "b": 2}}}}"#,
        );
    }

    #[test]
    fn private_keys_are_ignored() {
        check(json!({"__private": 1, "a": 1}), json!({"__private": 2, "a": 1}), "{}");
    }

    #[test]
    fn keys_with_quotes() {
        check(
            json!({"it's": 1, "say \"hi\"": 1}),
            json!({"it's": 2, "say \"hi\"": 2}),
            r#"{"values_changed": {"root[\"it's\"]": {"new_value": 2, "old_value": 1}, "root['say \"hi\"']": {"new_value": 2, "old_value": 1}}}"#,
        );
    }

    #[test]
    fn numbers_and_booleans() {
        check(
            json!({"n": 1, "f": 1.5, "b": true}),
            json!({"n": 1.0, "f": 2.5, "b": false}),
            r#"{"type_changes": {"root['n']": {"old_type": "int", "new_type": "float", "old_value": 1, "new_value": 1.0}}, "values_changed": {"root['f']": {"new_value": 2.5, "old_value": 1.5}, "root['b']": {"new_value": false, "old_value": true}}}"#,
        );
    }

    #[test]
    fn multiline_string_gets_unified_diff() {
        check(
            json!({"policy": "a\nb\nc"}),
            json!({"policy": "a\nB\nc\n"}),
            r#"{"values_changed": {"root['policy']": {"new_value": "a\nB\nc\n", "old_value": "a\nb\nc", "diff": "--- \n+++ \n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c"}}}"#,
        );
    }

    #[test]
    fn scalar_list_by_difflib_with_mutual_add_remove() {
        check(
            json!(["p", "q", "a", "b"]),
            json!(["a", "z", "b"]),
            r#"{"values_changed": {"root[1]": {"new_value": "z", "old_value": "q"}}, "iterable_item_removed": {"root[0]": "p"}}"#,
        );
    }

    #[test]
    fn scalar_list_replace_block_reports_new_path() {
        check(
            json!([2, "a"]),
            json!(["d", 2, 1.0]),
            r#"{"type_changes": {"root[1]": {"old_type": "str", "new_type": "float", "new_path": "root[2]", "old_value": "a", "new_value": 1.0}}, "iterable_item_added": {"root[0]": "d"}}"#,
        );
    }

    #[test]
    fn scalar_list_matches_numbers_across_types() {
        check(json!([1, 2]), json!([true, 2.0]), "{}");
        check(
            json!(["x", 1, "y", "z"]),
            json!(["w", "x", true, "y", "z"]),
            r#"{"iterable_item_added": {"root[0]": "w"}}"#,
        );
    }

    #[test]
    fn scalar_list_falls_back_to_index_pairs() {
        check(
            json!([1, 2, 3, 4, 5]),
            json!([5, 4, 3, 2, 1]),
            r#"{"values_changed": {"root[0]": {"new_value": 5, "old_value": 1}, "root[1]": {"new_value": 4, "old_value": 2}, "root[3]": {"new_value": 2, "old_value": 4}, "root[4]": {"new_value": 1, "old_value": 5}}}"#,
        );
    }

    #[test]
    fn list_of_dicts_compared_by_index() {
        check(
            json!([{"port": 80}, {"port": 443}]),
            json!([{"port": 80}, {"port": 8443}, {"port": 22}]),
            r#"{"values_changed": {"root[1]['port']": {"new_value": 8443, "old_value": 443}}, "iterable_item_added": {"root[2]": {"port": 22}}}"#,
        );
    }
}
