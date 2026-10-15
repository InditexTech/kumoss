// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, beforeEach } from "vitest";
import { makeStatus, makeRound, makeSessionDetail, mockState } from "./factories";

describe("makeStatus", () => {
  it("builds a StatusEntry with defaults", () => {
    const s = makeStatus("started");
    expect(s).toEqual({
      status: "started",
      message: null,
      created_at: "2026-01-01T00:00:00Z",
    });
  });

  it("accepts a custom message and timestamp", () => {
    const s = makeStatus("failed", "timeout", "2026-06-15T12:00:00Z");
    expect(s).toEqual({
      status: "failed",
      message: "timeout",
      created_at: "2026-06-15T12:00:00Z",
    });
  });
});

describe("makeRound", () => {
  it("returns a complete RoundDetail with bland defaults", () => {
    const r = makeRound();
    expect(r.query).toBe("deploy a VM");
    expect(r.number).toBe(1);
    expect(r.statuses).toHaveLength(2);
    expect(r.reports).toEqual([]);
    expect(r.compliance_checks).toEqual([]);
    expect(r.plans).toEqual([]);
    expect(r.code_changes).toEqual([]);
    expect(r.pull_requests).toEqual([]);
  });

  it("applies overrides", () => {
    const r = makeRound({ query: "create a bucket", number: 3 });
    expect(r.query).toBe("create a bucket");
    expect(r.number).toBe(3);
  });

  it("assigns incrementing ids", () => {
    const r1 = makeRound();
    const r2 = makeRound();
    expect(r2.id).toBeGreaterThan(r1.id);
  });
});

describe("makeSessionDetail", () => {
  it("returns a complete AdminSessionDetail", () => {
    const d = makeSessionDetail();
    expect(d.uuid).toBe("sess-1");
    expect(d.operation).toBe("generate");
    expect(d.provider).toBe("azure");
    expect(d.rounds).toHaveLength(1);
    expect(d.chat_history).toHaveLength(1);
    expect(d.history).toHaveLength(1);
    expect(d.workspace.uri).toContain("azure");
  });

  it("applies overrides deeply", () => {
    const d = makeSessionDetail({
      uuid: "custom-uuid",
      operation: "drift",
      provider: "gcp",
      rounds: [],
    });
    expect(d.uuid).toBe("custom-uuid");
    expect(d.operation).toBe("drift");
    expect(d.provider).toBe("gcp");
    expect(d.rounds).toEqual([]);
  });
});

describe("mockState", () => {
  beforeEach(() => mockState.clear());

  it("starts empty", () => {
    expect(mockState.listSessions()).toEqual([]);
  });

  it("adds and retrieves a session", () => {
    const detail = makeSessionDetail({ uuid: "a" });
    mockState.addSession(detail);
    expect(mockState.getSession("a")).toBe(detail);
  });

  it("returns undefined for unknown uuid", () => {
    expect(mockState.getSession("nope")).toBeUndefined();
  });

  it("lists all sessions", () => {
    mockState.addSession(makeSessionDetail({ uuid: "x" }));
    mockState.addSession(makeSessionDetail({ uuid: "y" }));
    expect(mockState.listSessions()).toHaveLength(2);
  });

  it("clear removes all sessions", () => {
    mockState.addSession(makeSessionDetail({ uuid: "z" }));
    mockState.clear();
    expect(mockState.listSessions()).toEqual([]);
  });

  it("addSession returns the detail it stored", () => {
    const detail = makeSessionDetail({ uuid: "ret" });
    const returned = mockState.addSession(detail);
    expect(returned).toBe(detail);
  });
});
