// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { normalizeHistory } from "./api";

describe("normalizeHistory", () => {
  it("returns [] for undefined input", () => {
    expect(normalizeHistory(undefined)).toEqual([]);
  });

  it("returns [] for empty array", () => {
    expect(normalizeHistory([])).toEqual([]);
  });

  it("converts backend {user, assistant} turn pairs into flat {role, content} entries", () => {
    const backend = [
      { user: "create a VM", assistant: "Here is the terraform code..." },
      { user: "add a database", assistant: "Done" },
    ];

    expect(normalizeHistory(backend)).toEqual([
      { role: "user", content: "create a VM" },
      { role: "assistant", content: "Here is the terraform code..." },
      { role: "user", content: "add a database" },
      { role: "assistant", content: "Done" },
    ]);
  });

  it("passes through entries already in {role, content} form", () => {
    const normalized = [
      { role: "user", content: "hello" },
      { role: "assistant", content: "hi" },
      { role: "validation", content: "Validating..." },
    ];

    expect(normalizeHistory(normalized)).toEqual(normalized);
  });

  it("handles mixed arrays with both shapes", () => {
    const mixed = [
      { role: "user", content: "already normalized" },
      { user: "from backend", assistant: "backend response" },
    ];

    expect(normalizeHistory(mixed)).toEqual([
      { role: "user", content: "already normalized" },
      { role: "user", content: "from backend" },
      { role: "assistant", content: "backend response" },
    ]);
  });

  it("skips entries that match neither shape", () => {
    const invalid = [{ something: "else" }, { user: "valid", assistant: "pair" }];

    expect(normalizeHistory(invalid)).toEqual([
      { role: "user", content: "valid" },
      { role: "assistant", content: "pair" },
    ]);
  });
});
