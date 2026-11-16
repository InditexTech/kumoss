// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { STRINGS } from "@/constants/strings";
import type {
  ManifestAnswers,
  ManifestProbeResponse,
  ManifestValue,
  ManifestVariable,
} from "@/types/api";

/** How a variable's value is entered, from its declared HCL type. */
export type InputKind = "bool" | "number" | "string" | "list" | "map" | "any";

const LIST_TYPES = ["list", "set", "tuple"];
const MAP_TYPES = ["map", "object"];

export function inputKind(type: string | null): InputKind {
  if (!type) return "any";
  const head = type.trim().replace(/^"|"$/g, "").split("(", 1)[0].trim();
  if (head === "bool" || head === "number" || head === "string") return head;
  if (LIST_TYPES.includes(head)) return "list";
  if (MAP_TYPES.includes(head)) return "map";
  return "any";
}

export type Parsed = { ok: true; value: ManifestValue } | { ok: false; error: string };

/**
 * The value typed for a variable of kind `kind`, or why it is not one.
 *
 * Only the outer shape is checked, as the server does; Terraform checks
 * nested types when it runs.
 */
export function parseInput(kind: InputKind, raw: string | boolean): Parsed {
  const S = STRINGS.wizard.inputs;
  if (kind === "bool") return { ok: true, value: raw === true };
  const text = typeof raw === "string" ? raw : String(raw);
  // Only asked variables reach here, all of which need a value: an empty
  // string is far likelier a slip than the intended value.
  if (!text.trim()) return { ok: false, error: S.required };
  if (kind === "string") return { ok: true, value: text };
  if (kind === "number") {
    const n = Number(text.trim());
    return Number.isFinite(n) ? { ok: true, value: n } : { ok: false, error: S.invalidNumber };
  }
  let parsed: ManifestValue;
  try {
    parsed = JSON.parse(text) as ManifestValue;
  } catch {
    return kind === "any" ? { ok: true, value: text } : { ok: false, error: S.invalidJson };
  }
  if (kind === "list" && !Array.isArray(parsed)) return { ok: false, error: S.wrongShape.list };
  if (
    kind === "map" &&
    (parsed === null || typeof parsed !== "object" || Array.isArray(parsed))
  ) {
    return { ok: false, error: S.wrongShape.map };
  }
  return { ok: true, value: parsed };
}

export interface InputsFormState {
  values: Record<string, string | boolean>;
  /** Store as secret, as toggled by the user (declared-sensitive ones are forced on). */
  secret: Record<string, boolean>;
  /** Selected var files, in the order they were picked. */
  varFiles: string[];
}

export function initialFormState(probe: ManifestProbeResponse): InputsFormState {
  return {
    values: Object.fromEntries(
      probe.missing_variables.map((v) => [v.name, inputKind(v.type) === "bool" ? false : ""]),
    ),
    secret: Object.fromEntries(probe.missing_variables.map((v) => [v.name, v.sensitive])),
    varFiles: probe.selectable_var_files.filter((f) => f.selected).map((f) => f.path),
  };
}

/** Pick or unpick `path`, keeping the picking order. */
export function toggleVarFile(selected: string[], path: string): string[] {
  return selected.includes(path) ? selected.filter((p) => p !== path) : [...selected, path];
}

/** The picked var file that sets each variable (the last picked wins, as in Terraform). */
export function setByVarFiles(
  probe: ManifestProbeResponse,
  state: InputsFormState,
): Map<string, string> {
  const sets = new Map(probe.selectable_var_files.map((f) => [f.path, f.sets]));
  const setBy = new Map<string, string>();
  for (const path of state.varFiles) {
    for (const name of sets.get(path) ?? []) setBy.set(name, path);
  }
  return setBy;
}

export type BuildResult =
  | { ok: true; answers: ManifestAnswers }
  | { ok: false; errors: Record<string, string> };

/** The answers to send, or the per-variable errors to show. */
export function buildAnswers(
  probe: ManifestProbeResponse,
  state: InputsFormState,
): BuildResult {
  const errors: Record<string, string> = {};
  const variables: ManifestAnswers["variables"] = [];
  const setBy = setByVarFiles(probe, state);
  for (const variable of probe.missing_variables) {
    const raw = state.values[variable.name] ?? "";
    // A picked var file answers it; a typed value would override the file.
    if (setBy.has(variable.name) && typeof raw === "string" && !raw.trim()) continue;
    const parsed = parseInput(inputKind(variable.type), raw);
    if (!parsed.ok) {
      errors[variable.name] = parsed.error;
      continue;
    }
    variables.push({
      name: variable.name,
      value: parsed.value,
      ...(isSecret(variable, state) && !variable.sensitive ? { sensitive: true } : {}),
    });
  }
  if (Object.keys(errors).length > 0) return { ok: false, errors };
  return {
    ok: true,
    answers: {
      variables,
      ...(probe.selectable_var_files.length > 0 ? { var_files: state.varFiles } : {}),
    },
  };
}

export function isSecret(variable: ManifestVariable, state: InputsFormState): boolean {
  return variable.sensitive || state.secret[variable.name] === true;
}

/** The type's head word (`object`, `list`, `string`…), or `any` when untyped. */
export function typeLabel(type: string | null): string {
  if (!type) return "any";
  return type.trim().replace(/^"|"$/g, "").split("(", 1)[0].trim() || "any";
}

/** Whether the declared type is worth showing in full (it has structure). */
export function hasStructure(type: string | null): boolean {
  return !!type && type.includes("(");
}

/**
 * A JSON example of a value of `type`, to show as a placeholder:
 * `object({ a = list(string) b = optional(bool, true) })` gives
 * `{"a": ["…"], "b": true}`. Best effort: unknown shapes give `null`.
 */
export function exampleFor(type: string | null): string | null {
  if (!type) return null;
  try {
    const value = exampleValue(type.trim().replace(/^"|"$/g, ""));
    return value === undefined ? null : JSON.stringify(value).replace(/,/g, ", ").replace(/:/g, ": ");
  } catch {
    return null;
  }
}

function exampleValue(type: string): ManifestValue | undefined {
  const open = type.indexOf("(");
  const head = (open < 0 ? type : type.slice(0, open)).trim();
  const inner = open < 0 ? "" : type.slice(open + 1, type.lastIndexOf(")")).trim();
  switch (head) {
    case "string":
      return "…";
    case "number":
      return 0;
    case "bool":
      return false;
    case "any":
      return undefined;
    case "list":
    case "set": {
      const item = exampleValue(inner);
      return item === undefined ? [] : [item];
    }
    case "tuple":
      return splitTopLevel(inner.replace(/^\[|\]$/g, ""), ",")
        .map((t) => exampleValue(t))
        .filter((v): v is ManifestValue => v !== undefined);
    case "map": {
      const item = exampleValue(inner);
      return { key: item === undefined ? "…" : item };
    }
    case "optional": {
      const [itemType, fallback] = splitTopLevel(inner, ",");
      if (fallback !== undefined) {
        try {
          return JSON.parse(fallback) as ManifestValue;
        } catch {
          /* not a JSON literal: fall back to the type's example */
        }
      }
      return exampleValue(itemType);
    }
    case "object": {
      const body = inner.replace(/^\{|\}$/g, "").trim();
      const out: Record<string, ManifestValue> = {};
      for (const [name, attrType] of objectAttributes(body)) {
        const value = exampleValue(attrType);
        if (value !== undefined) out[name] = value;
      }
      return out;
    }
    default:
      return undefined;
  }
}

/** Split on `sep` outside of (), [] and {}. */
function splitTopLevel(text: string, sep: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if ("([{".includes(c)) depth++;
    else if (")]}".includes(c)) depth--;
    else if (c === sep && depth === 0) {
      parts.push(text.slice(start, i).trim());
      start = i + 1;
    }
  }
  const last = text.slice(start).trim();
  if (last) parts.push(last);
  return parts;
}

/** `a = string b = list(number)` (one line, as the probe sends it) → pairs. */
function objectAttributes(body: string): Array<[string, string]> {
  const attrs: Array<[string, string]> = [];
  const re = /([A-Za-z_][A-Za-z0-9_-]*)\s*=\s*/g;
  const starts: Array<{ name: string; at: number; end: number }> = [];
  let m: RegExpExecArray | null;
  let depth = 0;
  let scanned = 0;
  while ((m = re.exec(body))) {
    for (; scanned < m.index; scanned++) {
      const c = body[scanned];
      if ("([{".includes(c)) depth++;
      else if (")]}".includes(c)) depth--;
    }
    if (depth === 0) starts.push({ name: m[1], at: m.index, end: re.lastIndex });
  }
  starts.forEach((s, i) => {
    const next = i + 1 < starts.length ? starts[i + 1].at : body.length;
    attrs.push([s.name, body.slice(s.end, next).trim().replace(/,$/, "")]);
  });
  return attrs;
}

/** Whether `variable` has a usable answer: a valid value, or a picked var file setting it. */
export function isAnswered(
  variable: ManifestVariable,
  state: InputsFormState,
  setBy: Map<string, string>,
): boolean {
  const raw = state.values[variable.name] ?? "";
  if (setBy.has(variable.name) && typeof raw === "string" && !raw.trim()) return true;
  return parseInput(inputKind(variable.type), raw).ok;
}
