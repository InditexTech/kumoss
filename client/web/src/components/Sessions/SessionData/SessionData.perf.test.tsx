// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Guards the per-round derivation against being pulled back into the
 * render body.
 *
 * `roundEvents` parses and sorts every status and artifact of a round.
 * `expandedStatuses` is component state, so the render body runs on every
 * expand/collapse — deriving there meant re-parsing the whole timeline to
 * open one row. Nothing else observes this, so it needs its own test.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { makeSessionDetail, makeRound, makeStatus } from "@/mocks/state";
import { renderWithProviders } from "@/test/render";
import SessionData from "./SessionData";
import { roundEvents } from "./roundSummary";

vi.mock("./roundSummary", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./roundSummary")>();
  return { ...actual, roundEvents: vi.fn(actual.roundEvents) };
});

function at(second: number): string {
  return `2026-01-01T00:00:${String(second).padStart(2, "0")}Z`;
}

/** Three rounds, each with an expandable status. */
function multiRoundSession() {
  return makeSessionDetail({
    current_status: "generating",
    in_flight: true,
    operation: "generate",
    rounds: [0, 1, 2].map((n) =>
      makeRound({
        id: n + 1,
        number: n + 1,
        statuses: [
          makeStatus("generating", `round ${n} detail`, at(n * 10)),
          makeStatus("validating", `round ${n} more`, at(n * 10 + 5)),
        ],
      }),
    ),
  });
}

describe("SessionData round derivation", () => {
  beforeEach(() => {
    vi.mocked(roundEvents).mockClear();
  });

  it("derives each round's events once per render, not once per call site", () => {
    renderWithProviders(<SessionData session={multiRoundSession()} />);

    // The heading's event count and the rows beneath it are the two
    // consumers; they must share one derivation.
    expect(vi.mocked(roundEvents)).toHaveBeenCalledTimes(3);
  });

  it("does not re-derive when a status row is expanded", async () => {
    renderWithProviders(<SessionData session={multiRoundSession()} />);
    vi.mocked(roundEvents).mockClear();

    const rows = screen.getAllByRole("button", { name: /Generating/ });
    await userEvent.click(rows[0]);
    expect(screen.getByText("round 0 detail")).toBeInTheDocument();

    await userEvent.click(rows[0]);

    // Two re-renders, both driven by state the derivation does not read.
    expect(vi.mocked(roundEvents)).not.toHaveBeenCalled();
  });
});
