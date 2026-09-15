// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import type { Session } from "@/types/ui";
import { isDriftSession } from "./session";

describe("isDriftSession", () => {
  // The API collapses full and partial drift into one `operation` value, so a
  // single check has to cover both drift modes and nothing else.
  const cases: Array<[Session["operation"], boolean]> = [
    ["drift", true],
    ["generate", false],
    ["import", false],
    [undefined, false],
  ];

  it.each(cases)("operation %s → %s", (operation, expected) => {
    expect(isDriftSession({ uuid: "sess-1", operation })).toBe(expected);
  });
});
