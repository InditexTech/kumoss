// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { extractProjectName } from "./workspace";

describe("extractProjectName", () => {
  it("takes the last URI segment", () => {
    expect(
      extractProjectName("https://dev.azure.com/org/project/_git/repo"),
    ).toBe("repo");
    expect(extractProjectName("https://host/repo/")).toBe("repo");
  });

  it("falls back to the input when there is no segment", () => {
    expect(extractProjectName("")).toBe("");
    expect(extractProjectName("/")).toBe("/");
  });
});
