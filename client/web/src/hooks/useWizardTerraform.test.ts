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
import { makeSessionDetail, makeRound, makeStatus } from "@/mocks/state";

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
    code: "<Terraform_Plan>\nplan output\n</Terraform_Plan>\n<main.tf>\nresource {}\n</main.tf>",
    targets: ["azurerm_resource_group.main"],
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
    expect(session.session_id).toBe("sess-1");
    expect(session.code).toContain("<main.tf>");
    expect(session.cloud).toBe("azure");
    expect(session.branchName).toBe("nebula/sess-1");
    expect(session.apply_allowed).toBe(true);
    expect(session.terraform_targets).toEqual(["azurerm_resource_group.main"]);
    // Rebuilt from {user, assistant} turns, plus the appended summary
    expect(session.full_history?.[0]).toEqual({
      role: "user",
      content: "deploy a VM",
    });
    expect(session.full_history?.[session.full_history.length - 1].role).toBe(
      "assistant",
    );
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

  it("rejected iteration appends the rationale as an assistant entry and keeps prior results", () => {
    const { result } = renderHook(
      () => ({
        terraform: useWizardTerraform(),
        session: useSession(),
      }),
      { wrapper: Wrapper },
    );

    act(() =>
      result.current.session.updateSession({
        session_id: "sess-1",
        code: "previous code",
        terraform_report: { status: "ok" },
      }),
    );

    const outcome: SessionOutcome = {
      kind: "rejected",
      detail: makeSessionDetail({ current_status: "uncompleted" }),
      rationale: "Query is off-topic",
    };

    act(() => result.current.terraform.handleOutcome(outcome));

    const session = result.current.session.session;
    expect(session.code).toBe("previous code");
    expect(session.terraform_report).toEqual({ status: "ok" });
    expect(session.full_history?.[session.full_history.length - 1]).toEqual({
      role: "assistant",
      content: "Query is off-topic",
    });
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

  it("keeps live wizard values over derived fallbacks", () => {
    const { result } = renderHook(
      () => ({
        terraform: useWizardTerraform(),
        session: useSession(),
      }),
      { wrapper: Wrapper },
    );

    act(() =>
      result.current.session.updateSession({
        project: "mapper-project",
        environment: "wizard/path",
      }),
    );

    act(() => result.current.terraform.handleOutcome(makeResultsOutcome()));

    expect(result.current.session.session.project).toBe("mapper-project");
    expect(result.current.session.session.environment).toBe("wizard/path");
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
