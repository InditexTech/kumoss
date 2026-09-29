// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import {
  formatDate,
  formatDateParts,
  formatDateTime,
  formatDuration,
} from "./datetime";

// These formatters read local-zone getters (`getDate`, `getHours`), so the
// fixtures are built in local time too. Constructing them from UTC would
// make every assertion depend on the machine's zone.
function local(y: number, m: number, d: number, h = 0, min = 0, s = 0): string {
  return new Date(y, m - 1, d, h, min, s).toISOString();
}

describe("formatDate", () => {
  it("renders day-first with zero padding", () => {
    expect(formatDate(local(2026, 3, 7))).toBe("07.03.2026");
  });

  it("renders the placeholder for a missing timestamp", () => {
    expect(formatDate(null)).toBe("-");
    expect(formatDate(undefined)).toBe("-");
    expect(formatDate("")).toBe("-");
  });

  it("renders the placeholder for an unparseable timestamp", () => {
    expect(formatDate("garbage")).toBe("-");
  });
});

describe("formatDateTime", () => {
  it("joins date and clock time", () => {
    expect(formatDateTime(local(2026, 12, 31, 9, 5))).toBe("31.12.2026, 09:05");
  });

  it("renders the placeholder for missing and unparseable input", () => {
    expect(formatDateTime(null)).toBe("-");
    expect(formatDateTime("not a date")).toBe("-");
  });
});

describe("formatDateParts", () => {
  it("splits the fields and shortens the year to two digits", () => {
    expect(formatDateParts(local(2026, 1, 9, 14, 30))).toEqual({
      date: "09.01.26",
      time: "14:30",
    });
  });

  it("leaves time empty so the placeholder shows once, not twice", () => {
    expect(formatDateParts(null)).toEqual({ date: "-", time: "" });
    expect(formatDateParts("garbage")).toEqual({ date: "-", time: "" });
  });
});

describe("formatDuration", () => {
  it("renders sub-minute ranges in seconds", () => {
    expect(
      formatDuration(local(2026, 1, 1, 0, 0, 0), local(2026, 1, 1, 0, 0, 45)),
    ).toBe("45s");
  });

  it("does not render a 60-second remainder", () => {
    // Flooring the minutes while rounding the remainder independently
    // produced "5m 60s" for this input. Rounding to whole seconds first
    // carries the extra second into the minute count.
    expect(
      formatDuration("2026-01-01T00:00:00.000Z", "2026-01-01T00:05:59.771Z"),
    ).toBe("6m 0s");
  });

  it("renders an exact minute with a zero remainder", () => {
    expect(
      formatDuration(local(2026, 1, 1, 0, 0, 0), local(2026, 1, 1, 0, 1, 0)),
    ).toBe("1m 0s");
  });

  it("renders the placeholder when the range runs backwards", () => {
    expect(
      formatDuration(local(2026, 1, 1, 0, 1, 0), local(2026, 1, 1, 0, 0, 0)),
    ).toBe("-");
  });

  it("renders the placeholder when either end is unparseable", () => {
    // `NaN < 0` is false, so an unguarded subtraction sails past the
    // backwards-range check and renders "NaNm NaNs".
    expect(formatDuration("garbage", local(2026, 1, 1))).toBe("-");
    expect(formatDuration(local(2026, 1, 1), "garbage")).toBe("-");
  });
});
