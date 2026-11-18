// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { nextStep } from "./wizardFlow";
import type { WizardData } from "./useWizardNavigation";

const EMPTY: WizardData = {
  query: "",
  repositoryUrl: "",
  rootModulePath: "",
  inputsChecked: false,
  inputs: null,
};

const data = (patch: Partial<WizardData>): WizardData => ({ ...EMPTY, ...patch });

describe("nextStep — first missing input wins", () => {
  it("asks for the query when nothing is collected", () => {
    expect(nextStep(EMPTY)).toBe("query");
  });

  it("asks for the repository once the query is in", () => {
    expect(nextStep(data({ query: "deploy a VM" }))).toBe("repository_url");
  });

  it("asks for the root module once the repository is in", () => {
    expect(
      nextStep(data({ query: "deploy a VM", repositoryUrl: "https://git.example/iac.git" })),
    ).toBe("root_module_path");
  });

  const filled = {
    query: "deploy a VM",
    repositoryUrl: "https://git.example/iac.git",
    rootModulePath: "environments/dev",
  };

  it("goes straight from the root module to the inputs: no provider or scope step", () => {
    expect(nextStep(data(filled))).toBe("inputs");
  });

  it("is complete only when every slot is filled and the inputs are checked", () => {
    expect(nextStep(data({ ...filled, inputsChecked: true }))).toBe("complete");
  });
});

// A step is skipped precisely because its slot is already filled — there
// is no skip rule, only "first input still missing".
describe("nextStep — after repository_url", () => {
  const resolved = {
    query: "deploy a VM",
    repositoryUrl: "https://git.example/iac.git",
  };

  it("a single root module (filled by the wizard) goes to the inputs", () => {
    expect(nextStep(data({ ...resolved, rootModulePath: "environments/dev" }))).toBe("inputs");
  });

  it("several root modules ask for the path first", () => {
    expect(nextStep(data(resolved))).toBe("root_module_path");
  });
});

describe("nextStep — never yields a removed step", () => {
  const samples: WizardData[] = [
    EMPTY,
    data({ query: "q" }),
    data({ query: "q", repositoryUrl: "r" }),
    data({ query: "q", repositoryUrl: "r", rootModulePath: "p" }),
    data({ query: "q", repositoryUrl: "r", rootModulePath: "p", inputsChecked: true }),
  ];

  it.each(samples)("%#", (sample) => {
    expect(["provider", "scope"]).not.toContain(nextStep(sample));
  });
});
