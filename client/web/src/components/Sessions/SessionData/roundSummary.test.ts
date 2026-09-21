// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import type {
  CodeChangeRef,
  ReportRef,
  ReportType,
  RoundDetail,
  SessionDetail,
  SessionStatus,
  StatusEntry,
  TerraformPlanRef,
} from "@/types/api";
import { roundEvents, roundMeta, roundTitle } from "./roundSummary";

// Seconds past a fixed epoch, so a test reads as a sequence of moments.
function at(second: number): string {
  return new Date(Date.UTC(2026, 0, 1, 12, 0, second)).toISOString();
}

function status(
  s: SessionStatus,
  second: number,
  message: string | null = null,
): StatusEntry {
  return { status: s, message, created_at: at(second) };
}

const artifactBase = {
  url: "https://storage.example.com/a",
  content_type: "text/plain",
  file_size_bytes: 10,
};

function change(id: number, file_name: string, second: number): CodeChangeRef {
  return { ...artifactBase, id, file_name, created_at: at(second) };
}

function plan(id: number, second: number): TerraformPlanRef {
  return { ...artifactBase, id, targets: [], created_at: at(second) };
}

function report(id: number, type: ReportType, second: number): ReportRef {
  return { ...artifactBase, id, type, created_at: at(second) };
}

function round(overrides: Partial<RoundDetail> = {}): RoundDetail {
  return {
    id: 1,
    number: 1,
    query: "Create a storage account",
    statuses: [],
    reports: [],
    plans: [],
    code_changes: [],
    pull_requests: [],
    created_at: at(0),
    ...overrides,
  };
}

describe("roundEvents", () => {
  it("emits one event per status, in chronological order", () => {
    const events = roundEvents(
      round({
        statuses: [
          status("filtering", 0),
          status("generating", 10),
          status("completed", 20),
        ],
      }),
    );

    expect(events.map((e) => e.status)).toEqual([
      "filtering",
      "generating",
      "completed",
    ]);
    expect(events.every((e) => e.artifacts.length === 0)).toBe(true);
  });

  it("carries each status's message on its event", () => {
    const events = roundEvents(
      round({ statuses: [status("failed", 0, "state lock held")] }),
    );

    expect(events[0].message).toBe("state lock held");
  });

  it("attaches code changes to the generating status that produced them", () => {
    const events = roundEvents(
      round({
        statuses: [
          status("generating", 10),
          status("validating", 30),
          status("completed", 40),
        ],
        code_changes: [change(1, "main.tf", 15), change(2, "vars.tf", 20)],
      }),
    );

    expect(events[0].artifacts.map((a) => a.artifact.id)).toEqual([1, 2]);
    expect(events[1].artifacts).toEqual([]);
    expect(events[2].artifacts).toEqual([]);
  });

  it("splits a repeated generate/validate loop's files across their own pass", () => {
    const events = roundEvents(
      round({
        statuses: [
          status("generating", 10),
          status("validating", 20),
          status("generating", 30),
          status("validating", 40),
        ],
        code_changes: [change(1, "main.tf", 15), change(2, "main.tf", 35)],
      }),
    );

    expect(events[0].artifacts.map((a) => a.artifact.id)).toEqual([1]);
    expect(events[2].artifacts.map((a) => a.artifact.id)).toEqual([2]);
  });

  it("attaches the plan to its validating status and the report to its report status", () => {
    const events = roundEvents(
      round({
        statuses: [
          status("validating", 10),
          status("report", 30),
          status("completed", 50),
        ],
        plans: [plan(7, 20)],
        reports: [report(9, "generate", 40)],
      }),
    );

    expect(events[0].artifacts).toEqual([
      { kind: "plan", artifact: expect.objectContaining({ id: 7 }) },
    ]);
    expect(events[1].artifacts).toEqual([
      { kind: "report", artifact: expect.objectContaining({ id: 9 }) },
    ]);
    expect(events[2].artifacts).toEqual([]);
  });

  it("treats an artifact stamped at its status's instant as belonging to it", () => {
    const events = roundEvents(
      round({
        statuses: [status("generating", 10), status("validating", 20)],
        code_changes: [change(1, "main.tf", 10)],
      }),
    );

    expect(events[0].artifacts.map((a) => a.artifact.id)).toEqual([1]);
    expect(events[1].artifacts).toEqual([]);
  });

  it("clamps an artifact older than every status onto the first event", () => {
    const events = roundEvents(
      round({
        statuses: [status("generating", 10)],
        code_changes: [change(1, "main.tf", 5)],
      }),
    );

    expect(events[0].artifacts.map((a) => a.artifact.id)).toEqual([1]);
  });

  it("emits nothing for a round whose first status is not written yet", () => {
    expect(roundEvents(round({ statuses: [] }))).toEqual([]);
  });
});

describe("roundMeta", () => {
  it("counts the round's events, not its files and artifacts", () => {
    const meta = roundMeta(
      round({
        statuses: [
          status("generating", 10),
          status("validating", 30),
          status("completed", 50),
        ],
        code_changes: [change(1, "main.tf", 15), change(2, "vars.tf", 20)],
        plans: [plan(3, 35)],
      }),
    );

    expect(meta).toEqual(["3 EVENTS"]);
  });

  it("keeps the count singular for a one-event round", () => {
    expect(roundMeta(round({ statuses: [status("filtering", 0)] }))).toEqual([
      "1 EVENT",
    ]);
  });

  it("omits the count for a round with no events", () => {
    expect(roundMeta(round({ statuses: [] }))).toEqual([]);
  });
});

describe("roundEvents with multiple plans", () => {
  it("gives each validation pass the plan it produced", () => {
    const events = roundEvents(
      round({
        statuses: [
          status("validating", 10),
          status("reconciling", 30),
          status("validating", 50),
        ],
        plans: [plan(1, 15), plan(2, 35), plan(3, 55)],
      }),
    );

    expect(events[0].artifacts.map((a) => a.artifact.id)).toEqual([1]);
    expect(events[1].artifacts.map((a) => a.artifact.id)).toEqual([2]);
    expect(events[2].artifacts.map((a) => a.artifact.id)).toEqual([3]);
  });

  it("keeps several plans on one status in chronological order", () => {
    const events = roundEvents(
      round({
        statuses: [status("validating", 10), status("report", 60)],
        plans: [plan(2, 30), plan(1, 20)],
      }),
    );

    expect(events[0].artifacts.map((a) => a.artifact.id)).toEqual([1, 2]);
  });
});

function driftSession(): SessionDetail {
  return {
    uuid: "sess-1",
    username: "user@test.com",
    operation: "drift",
    provider: "azure",
    first_query: "check for drift",
    workspace_uri: "https://github.com/contoso/infra",
    current_status: "completed",
    in_flight: false,
    is_blocked: false,
    created_at: at(0),
    updated_at: at(60),
    workspace: {
      uri: "https://github.com/contoso/infra",
      branch: "nebula/sess-1",
      root_path: null,
    },
    scope_id: "sub-123",
    rounds: [],
    history: [],
  };
}

function targetedPlan(id: number, second: number, targets: string[]) {
  return { ...plan(id, second), targets };
}

describe("roundTitle partial drift", () => {
  it("marks a drift round partial when any plan carries targets", () => {
    // The handler writes the drift diff and its plan with the partial
    // targets, then the nested validation service appends plans whose
    // targets come from the LLM validator and are usually empty. Reading
    // only the newest plan loses the suffix.
    const title = roundTitle(
      round({
        statuses: [status("validating", 10)],
        reports: [report(1, "drift", 20)],
        plans: [
          targetedPlan(1, 12, ["azurerm_virtual_machine.a"]),
          targetedPlan(2, 14, ["azurerm_virtual_machine.a"]),
          targetedPlan(3, 16, []),
        ],
      }),
      driftSession(),
    );

    expect(title).toBe("Drift Analysis (partial)");
  });

  it("leaves a full drift round unmarked", () => {
    const title = roundTitle(
      round({
        statuses: [status("validating", 10)],
        reports: [report(1, "drift", 20)],
        plans: [targetedPlan(1, 12, [])],
      }),
      driftSession(),
    );

    expect(title).toBe("Drift Analysis");
  });
});
