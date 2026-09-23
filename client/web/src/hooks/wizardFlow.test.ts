// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { nextStep } from "./wizardFlow";
import type { WizardData } from "./useWizardNavigation";

const EMPTY: WizardData = {
  query: "",
  repositoryUrl: "",
  provider: "",
  cloudScope: "",
  iacPath: "",
};

const data = (patch: Partial<WizardData>): WizardData => ({ ...EMPTY, ...patch });

describe("nextStep — first missing input wins", () => {
  it("asks for the query when nothing is collected", () => {
    expect(nextStep(EMPTY)).toBe("query");
  });

  it("asks for the repository once the query is in", () => {
    expect(nextStep(data({ query: "deploy a VM" }))).toBe("repository_url");
  });

  it("is complete only when every slot is filled", () => {
    expect(
      nextStep(
        data({
          query: "deploy a VM",
          repositoryUrl: "https://git.example/iac.git",
          iacPath: "environments/dev",
          provider: "azure",
          cloudScope: "sub-123",
        }),
      ),
    ).toBe("complete");
  });
});

// What the mapper answers decides what the user is asked. A step is
// skipped precisely because its slot is already filled — there is no
// skip rule, only "first input still missing".
describe("nextStep — the skip matrix after repository_url", () => {
  const resolved = {
    query: "deploy a VM",
    repositoryUrl: "https://git.example/iac.git",
  };

  const cases: Array<{
    name: string;
    paths: number;
    provider: WizardData["provider"];
    scope: string;
    expected: ReturnType<typeof nextStep>;
  }> = [
    // Single IaC path: the wizard fills iacPath itself, so what the
    // mapper answered is all that is left to decide.
    {
      name: "single path, mapper answered neither",
      paths: 1,
      provider: "",
      scope: "",
      expected: "provider",
    },
    {
      name: "single path, mapper answered provider only",
      paths: 1,
      provider: "azure",
      scope: "",
      expected: "cloud_scope",
    },
    {
      name: "single path, mapper answered scope only",
      paths: 1,
      provider: "",
      scope: "sub-123",
      expected: "provider",
    },
    {
      name: "single path, mapper answered both",
      paths: 1,
      provider: "azure",
      scope: "sub-123",
      expected: "complete",
    },
    // Multi-path repos insert iac_path first, whatever the mapper said.
    {
      name: "multi path, mapper answered neither",
      paths: 2,
      provider: "",
      scope: "",
      expected: "iac_path",
    },
    {
      name: "multi path, mapper answered provider only",
      paths: 2,
      provider: "azure",
      scope: "",
      expected: "iac_path",
    },
    {
      name: "multi path, mapper answered scope only",
      paths: 2,
      provider: "",
      scope: "sub-123",
      expected: "iac_path",
    },
    {
      name: "multi path, mapper answered both",
      paths: 2,
      provider: "azure",
      scope: "sub-123",
      expected: "iac_path",
    },
  ];

  it.each(cases)("$name → $expected", ({ paths, provider, scope, expected }) => {
    expect(
      nextStep(
        data({
          ...resolved,
          iacPath: paths === 1 ? "environments/dev" : "",
          provider,
          cloudScope: scope,
        }),
      ),
    ).toBe(expected);
  });
});

// Once the path is chosen, a multi-path repo behaves like a single-path
// one: the remaining steps are exactly the slots the mapper left empty.
describe("nextStep — after iac_path is chosen", () => {
  const chosen = {
    query: "deploy a VM",
    repositoryUrl: "https://git.example/iac.git",
    iacPath: "environments/pro",
  };

  it.each([
    { provider: "" as const, scope: "", expected: "provider" },
    { provider: "gcp" as const, scope: "", expected: "cloud_scope" },
    { provider: "" as const, scope: "my-project", expected: "provider" },
    { provider: "gcp" as const, scope: "my-project", expected: "complete" },
  ])(
    "provider=$provider scope=$scope → $expected",
    ({ provider, scope, expected }) => {
      expect(
        nextStep(data({ ...chosen, provider, cloudScope: scope })),
      ).toBe(expected);
    },
  );
});

// A scope without a provider must not skip the provider step: the scope
// prompt is worded per provider, and the plan needs both.
describe("nextStep — a scope alone never completes the wizard", () => {
  it("still asks for the provider", () => {
    expect(
      nextStep(
        data({
          query: "deploy a VM",
          repositoryUrl: "https://git.example/iac.git",
          iacPath: "environments/dev",
          cloudScope: "ocid1.compartment.oc1..aaaa",
        }),
      ),
    ).toBe("provider");
  });
});
