// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import {
  buildAnswers,
  exampleFor,
  hasStructure,
  initialFormState,
  inputKind,
  isAnswered,
  parseInput,
  toggleVarFile,
  typeLabel,
} from "./manifestInputs";
import type { ManifestProbeResponse } from "@/types/api";

const PROBE: ManifestProbeResponse = {
  status: "not_found",
  needs_input: true,
  missing_variables: [
    { name: "region", type: "map(string)", description: "", required: true, sensitive: false },
    { name: "db_password", type: "string", description: "", required: true, sensitive: true },
    { name: "replicas", type: "number", description: "", required: true, sensitive: false },
    { name: "enabled", type: "bool", description: "", required: true, sensitive: false },
  ],
  selectable_var_files: [
    { path: "envs/dev.tfvars", sets: ["region", "enabled"] },
    { path: "envs/pro.tfvars", sets: [] },
  ],
  selected_var_files: ["envs/pro.tfvars"],
  missing_var_files: [],
  provider_changes: [],
};

describe("inputKind", () => {
  it.each([
    ["string", "string"],
    ["number", "number"],
    ["bool", "bool"],
    ["list(string)", "list"],
    ["set(number)", "list"],
    ["tuple([string, number])", "list"],
    ["map(string)", "map"],
    ["object({ a = string })", "map"],
    ['"list"', "list"],
    ["any", "any"],
    [null, "any"],
  ] as const)("%s → %s", (type, kind) => {
    expect(inputKind(type)).toBe(kind);
  });
});

describe("parseInput", () => {
  it("parses each kind to its JSON value", () => {
    expect(parseInput("string", "westeurope")).toEqual({ ok: true, value: "westeurope" });
    expect(parseInput("number", " 3 ")).toEqual({ ok: true, value: 3 });
    expect(parseInput("bool", true)).toEqual({ ok: true, value: true });
    expect(parseInput("list", '["a", "b"]')).toEqual({ ok: true, value: ["a", "b"] });
    expect(parseInput("map", '{"location": "x"}')).toEqual({ ok: true, value: { location: "x" } });
    expect(parseInput("any", "[1]")).toEqual({ ok: true, value: [1] });
    expect(parseInput("any", "plain text")).toEqual({ ok: true, value: "plain text" });
  });

  it("rejects blanks and wrong shapes", () => {
    expect(parseInput("string", "  ").ok).toBe(false);
    expect(parseInput("number", "three").ok).toBe(false);
    expect(parseInput("list", '{"a": 1}').ok).toBe(false);
    expect(parseInput("map", "[1]").ok).toBe(false);
    expect(parseInput("map", "null").ok).toBe(false);
    expect(parseInput("map", "{oops").ok).toBe(false);
  });
});

describe("var file selection", () => {
  it("starts from the current selection and keeps the picking order", () => {
    const state = initialFormState(PROBE);
    expect(state.varFiles).toEqual(["envs/pro.tfvars"]);
    const picked = toggleVarFile(state.varFiles, "envs/dev.tfvars");
    expect(picked).toEqual(["envs/pro.tfvars", "envs/dev.tfvars"]);
    expect(toggleVarFile(picked, "envs/pro.tfvars")).toEqual(["envs/dev.tfvars"]);
  });

  it("keeps the saved order, not the listing order", () => {
    const probe = { ...PROBE, selected_var_files: ["envs/pro.tfvars", "envs/dev.tfvars"] };
    expect(initialFormState(probe).varFiles).toEqual(["envs/pro.tfvars", "envs/dev.tfvars"]);
  });
});

describe("buildAnswers", () => {
  it("builds typed answers, flagging only user-chosen secrets", () => {
    const state = initialFormState(PROBE);
    state.values = {
      region: '{"location": "westeurope"}',
      db_password: "s3cr3t",
      replicas: "2",
      enabled: true,
    };
    state.secret.replicas = true;

    expect(buildAnswers(PROBE, state)).toEqual({
      ok: true,
      answers: {
        variables: [
          { name: "region", value: { location: "westeurope" } },
          // Declared sensitive: the server forces it, nothing to send.
          { name: "db_password", value: "s3cr3t" },
          { name: "replicas", value: 2, sensitive: true },
          { name: "enabled", value: true },
        ],
        var_files: ["envs/pro.tfvars"],
      },
    });
  });

  it("reports every invalid value at once", () => {
    const state = initialFormState(PROBE);
    state.values.region = "westeurope";
    const result = buildAnswers(PROBE, state);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(Object.keys(result.errors).sort()).toEqual(["db_password", "region", "replicas"]);
    }
  });

  it("a picked var file answers the variables it sets, unless one is typed", () => {
    const state = initialFormState(PROBE);
    state.values = { region: "", db_password: "pw", replicas: "1", enabled: false };

    // Not picked: region is still required.
    expect(buildAnswers(PROBE, state).ok).toBe(false);

    state.varFiles = ["envs/dev.tfvars"];
    const fromFile = buildAnswers(PROBE, state);
    expect(fromFile.ok && fromFile.answers.variables.map((v) => v.name)).toEqual([
      "db_password",
      "replicas",
      "enabled",
    ]);

    state.values.region = '{"location": "override"}';
    const typed = buildAnswers(PROBE, state);
    expect(typed.ok && typed.answers.variables[0]).toEqual({
      name: "region",
      value: { location: "override" },
    });
  });

  it("sends no var_files when the module has none to choose from", () => {
    const probe = {
      ...PROBE,
      missing_variables: [],
      selectable_var_files: [],
      selected_var_files: [],
    };
    expect(buildAnswers(probe, initialFormState(probe))).toEqual({
      ok: true,
      answers: { variables: [] },
    });
  });

  it("clears a selection whose files are all gone", () => {
    const probe = {
      ...PROBE,
      missing_variables: [],
      selectable_var_files: [],
      selected_var_files: [],
      missing_var_files: ["envs/old.tfvars"],
    };
    expect(buildAnswers(probe, initialFormState(probe))).toEqual({
      ok: true,
      answers: { variables: [], var_files: [] },
    });
  });

  it("leaves an untouched switch to the picked var file that sets it", () => {
    const state = initialFormState(PROBE);
    state.values = { ...state.values, db_password: "pw", replicas: "1" };
    state.varFiles = ["envs/dev.tfvars"];
    state.values.region = "";
    const fromFile = buildAnswers(PROBE, state);
    expect(fromFile.ok && fromFile.answers.variables.map((v) => v.name)).toEqual([
      "db_password",
      "replicas",
    ]);

    // Not covered by a file: an untouched switch is sent as off.
    state.varFiles = [];
    state.values.region = '{"a": "b"}';
    const noFile = buildAnswers(PROBE, state);
    expect(noFile.ok && noFile.answers.variables[noFile.answers.variables.length - 1]).toEqual({ name: "enabled", value: false });

    // Switched (even back off): the user's choice wins over the file.
    state.varFiles = ["envs/dev.tfvars"];
    state.values.enabled = false;
    const touched = buildAnswers(PROBE, state);
    expect(touched.ok && touched.answers.variables[touched.answers.variables.length - 1]).toEqual({ name: "enabled", value: false });
  });
});

describe("typeLabel / hasStructure", () => {
  it("names the type's head word", () => {
    expect(typeLabel("object({ a = string })")).toBe("object");
    expect(typeLabel("list(string)")).toBe("list");
    expect(typeLabel("string")).toBe("string");
    expect(typeLabel(null)).toBe("any");
    expect(hasStructure("list(string)")).toBe(true);
    expect(hasStructure("string")).toBe(false);
  });
});

describe("exampleFor", () => {
  it.each([
    ["list(string)", '["…"]'],
    ["map(number)", '{"key": 0}'],
    ["set(bool)", "[false]"],
    ["tuple([string, number])", '["…", 0]'],
    [
      "object({ allowed_ip_ranges = list(string) bypass_azure_services = optional(bool, true) })",
      '{"allowed_ip_ranges": ["…"], "bypass_azure_services": true}',
    ],
    ["object({ a = object({ b = map(string) }) c = number })", '{"a": {"b": {"key": "…"}}, "c": 0}'],
  ])("%s → %s", (type, example) => {
    expect(exampleFor(type)).toBe(example);
  });

  it("gives nothing for untyped or unknown shapes", () => {
    expect(exampleFor(null)).toBeNull();
    expect(exampleFor("any")).toBeNull();
  });
});

describe("isAnswered", () => {
  it("counts valid values and picked var files", () => {
    const state = initialFormState(PROBE);
    const region = PROBE.missing_variables[0];
    expect(isAnswered(region, state, new Map())).toBe(false);
    expect(isAnswered(region, state, new Map([["region", "envs/dev.tfvars"]]))).toBe(true);
    state.values.region = "[1]";
    expect(isAnswered(region, state, new Map())).toBe(false);
    state.values.region = '{"a": "b"}';
    expect(isAnswered(region, state, new Map())).toBe(true);
  });
});
