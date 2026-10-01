// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { SessionProvider, useSession } from "@/contexts/SessionContext";
import { NotificationProvider } from "@/contexts/NotificationContext";
import { useWizardTerraform } from "./useWizardTerraform";
import { invalidateSessionsCache } from "@/services/core/sessionsCache";
import type { SessionOutcome } from "@/services/workflows/session_outcome";
import { makeSessionDetail, makeRound, makeStatus } from "@/test/factories";

vi.mock("@/services/core/sessionsCache", () => ({
  invalidateSessionsCache: vi.fn(),
}));

function Wrapper({ children }: { children: React.ReactNode }) {
  return React.createElement(
    MemoryRouter,
    { initialEntries: ["/home"] },
    React.createElement(
      SessionProvider,
      null,
      React.createElement(NotificationProvider, null, children),
    ),
  );
}

function makeResultsOutcome(
  overrides?: Partial<Extract<SessionOutcome, { kind: "results" }>>,
): SessionOutcome {
  const detail = makeSessionDetail();
  return {
    kind: "results",
    detail,
    round: detail.rounds[0],
    report: null,
    compliance: null,
    code: "<Terraform_Plan>\nplan output\n</Terraform_Plan>\n<main.tf>\nresource {}\n</main.tf>",
    ...overrides,
  };
}

describe("useWizardTerraform — handleOutcome", () => {
  beforeEach(() => {
    vi.mocked(invalidateSessionsCache).mockClear();
  });

  it("results outcome stores code, report fields and rebuilt history", () => {
    const { result } = renderHook(
      () => ({
        terraform: useWizardTerraform(),
        session: useSession(),
      }),
      { wrapper: Wrapper },
    );

    const outcome = makeResultsOutcome();

    act(() => result.current.terraform.handleOutcome(outcome));

    const session = result.current.session.session;
    expect(session.uuid).toBe("sess-1");
    expect(session.code).toContain("<main.tf>");
    expect(session.provider).toBe("azure");
    expect(session.workspace?.branch).toBe("nebula/sess-1");
    expect(session.is_blocked).toBe(false);
    // Flattened from the backend's `chat_history` turns; the hook adds
    // nothing of its own.
    expect(session.history).toEqual([
      { role: "user", content: "deploy a VM" },
      {
        role: "assistant",
        content: "Done: the plan adds one VM. Need anything else?",
      },
    ]);
  });

  it("apply-results outcome sets applyResults from the apply report", () => {
    const { result } = renderHook(
      () => ({
        terraform: useWizardTerraform(),
        session: useSession(),
      }),
      { wrapper: Wrapper },
    );

    const detail = makeSessionDetail({
      rounds: [
        makeRound({
          statuses: [makeStatus("apply"), makeStatus("completed")],
        }),
      ],
    });
    const outcome: SessionOutcome = {
      kind: "apply-results",
      detail,
      round: detail.rounds[0],
      report: {
        status: "Success",
        execution_summary: "Applied successfully",
      },
    };

    act(() => result.current.terraform.handleOutcome(outcome));

    const applyResults = result.current.session.session.applyResults;
    expect(applyResults).toBeDefined();
    expect(applyResults!.sessionId).toBe("sess-1");
    expect(applyResults!.status).toBe("Success");
    expect(applyResults!.message).toBe("Applied successfully");
    expect(applyResults!.applyReport).toEqual(outcome.report);
  });

  it("rejected iteration shows the stored rationale and keeps prior results", () => {
    const { result } = renderHook(
      () => ({
        terraform: useWizardTerraform(),
        session: useSession(),
      }),
      { wrapper: Wrapper },
    );

    act(() =>
      result.current.session.updateSession({
        uuid: "sess-1",
        code: "previous code",
        terraform_report: { status: "ok" },
      }),
    );

    // A rejected round's turn is written by the backend like any other:
    // its reply is the rationale, stored unchanged.
    const outcome: SessionOutcome = {
      kind: "rejected",
      detail: makeSessionDetail({
        current_status: "uncompleted",
        chat_history: [
          { user: "deploy a bitcoin miner", assistant: "Query is off-topic" },
        ],
      }),
      rationale: "Query is off-topic",
    };

    act(() => result.current.terraform.handleOutcome(outcome));

    const session = result.current.session.session;
    expect(session.code).toBe("previous code");
    expect(session.terraform_report).toEqual({ status: "ok" });
    expect(session.history?.[session.history.length - 1]).toEqual({
      role: "assistant",
      content: "Query is off-topic",
    });
  });

  it("rejected first round appends the rationale with no artifacts in context", () => {
    const { result } = renderHook(
      () => ({
        terraform: useWizardTerraform(),
        session: useSession(),
      }),
      { wrapper: Wrapper },
    );

    const outcome: SessionOutcome = {
      kind: "rejected",
      detail: makeSessionDetail({
        current_status: "uncompleted",
        chat_history: [
          { user: "deploy a bitcoin miner", assistant: "Query is off-topic" },
        ],
      }),
      rationale: "Query is off-topic",
    };

    act(() => result.current.terraform.handleOutcome(outcome));

    // No code/report → the results route renders the history panel chat-only
    const session = result.current.session.session;
    expect(session.uuid).toBe("sess-1");
    expect(session.code).toBeUndefined();
    expect(session.terraform_report).toBeUndefined();
    expect(session.history?.[session.history.length - 1]).toEqual({
      role: "assistant",
      content: "Query is off-topic",
    });
  });

  it("never synthesizes a turn the conversation does not carry", () => {
    const { result } = renderHook(
      () => ({
        terraform: useWizardTerraform(),
        session: useSession(),
      }),
      { wrapper: Wrapper },
    );

    // A round whose chat reply could not be inferred has no turn at all.
    // The hook shows the conversation as stored rather than filling the
    // gap with a client-side summary.
    const outcome: SessionOutcome = {
      kind: "rejected",
      detail: makeSessionDetail({
        current_status: "uncompleted",
        chat_history: [],
      }),
      rationale: "Query is off-topic",
    };

    act(() => result.current.terraform.handleOutcome(outcome));

    expect(result.current.session.session.history).toEqual([]);
  });

  it("failed outcome marks the session unresumable", () => {
    const { result } = renderHook(
      () => ({
        terraform: useWizardTerraform(),
        session: useSession(),
      }),
      { wrapper: Wrapper },
    );

    const outcome: SessionOutcome = {
      kind: "failed",
      detail: null,
      message: "Process failed",
    };

    act(() => result.current.terraform.handleOutcome(outcome));

    expect(result.current.session.session.current_status).toBe("failed");
  });

  it("replaces the wizard's partial workspace with the backend's facts", () => {
    const { result } = renderHook(
      () => ({
        terraform: useWizardTerraform(),
        session: useSession(),
      }),
      { wrapper: Wrapper },
    );

    act(() =>
      result.current.session.updateSession({
        workspace: {
          uri: "https://dev.azure.com/org/project/_git/repo",
          root_path: "environments/dev",
        },
      }),
    );

    act(() => result.current.terraform.handleOutcome(makeResultsOutcome()));

    expect(result.current.session.session.workspace).toEqual({
      uri: "https://dev.azure.com/org/project/_git/repo",
      branch: "nebula/sess-1",
      root_path: "environments/dev",
    });
  });

  it("invalidates the sessions cache on every outcome", () => {
    const { result } = renderHook(
      () => ({ terraform: useWizardTerraform() }),
      { wrapper: Wrapper },
    );

    act(() => result.current.terraform.handleOutcome(makeResultsOutcome()));

    expect(invalidateSessionsCache).toHaveBeenCalledOnce();
  });
});
