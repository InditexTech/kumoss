// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { Routes, Route, Outlet, useLocation } from "react-router-dom";
import React, { useEffect, useState } from "react";
import { useSession } from "@/contexts/SessionContext";
import { renderWithProviders } from "@/test/render";
import {
  mockState,
  makeSessionDetail,
  makeRound,
  makeStatus,
} from "@/mocks/state";
import ResultsRoute from "./ResultsRoute";

vi.mock("@/services/core/iac_code", () => ({
  createPullRequest: vi.fn(),
  mergePullRequest: vi.fn(),
}));

const iterate = vi.fn();
const applyAfterPr = vi.fn();
const resume = vi.fn();

function LayoutStub() {
  const context = {
    view: "result" as const,
    isSplitView: true,
    handleContactTeam: vi.fn(),
    wizard: { iterate, applyAfterPr, resume },
  };
  return <Outlet context={context} />;
}

/** Surfaces the live URL so tests can assert on navigation side effects. */
function LocationProbe() {
  const { pathname, search } = useLocation();
  return <div data-testid="location">{`${pathname}${search}`}</div>;
}

/** Applies the session patch BEFORE mounting the route, so
 *  useSessionLoader sees the session as already loaded and skips
 *  the deep-link refetch. */
function SessionGate({ patch, pr, children }: {
  patch: Record<string, unknown>;
  pr?: Record<string, unknown>;
  children: React.ReactNode;
}) {
  const { updateSession, updatePrDetails } = useSession();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    updateSession(patch);
    if (pr) updatePrDetails(pr);
    setReady(true);
  }, []);
  return ready ? <>{children}</> : null;
}

function renderRoute(
  sessionPatch: Record<string, unknown>,
  options?: { pr?: Record<string, unknown>; entry?: string },
) {
  return renderWithProviders(
    <SessionGate patch={{ uuid: "sess-1", ...sessionPatch }} pr={options?.pr}>
      <LocationProbe />
      <Routes>
        <Route element={<LayoutStub />}>
          <Route path="/home/results/:sessionId" element={<ResultsRoute />} />
        </Route>
      </Routes>
    </SessionGate>,
    {
      withNotifications: true,
      routerProps: {
        initialEntries: [options?.entry ?? "/home/results/sess-1"],
      },
    },
  );
}

describe("ResultsRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders chat-only without artifacts (rejected round)", () => {
    renderRoute({
      current_status: "uncompleted",
      history: [
        { role: "user", content: "deploy a bitcoin miner" },
        { role: "assistant", content: "Query is off-topic" },
      ],
    });

    // History panel with the rejection rationale, input ready for a reply
    expect(screen.getByText("Query is off-topic")).toBeInTheDocument();
    expect(screen.getByLabelText("Follow-up question")).toBeEnabled();

    // No result panel and no artifact actions to act on
    expect(screen.queryByRole("button", { name: "Report" })).not.toBeInTheDocument();
    expect(screen.queryByText("View Report")).not.toBeInTheDocument();
    expect(screen.queryByText("Create PR")).not.toBeInTheDocument();
  });

  it("keeps the split view for a rejected iteration with prior artifacts", () => {
    renderRoute({
      current_status: "uncompleted",
      code: "<main.tf>\nresource {}\n</main.tf>",
      history: [
        { role: "user", content: "deploy a VM" },
        { role: "assistant", content: "Query is off-topic" },
      ],
    });

    expect(screen.getByText("Query is off-topic")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Report" })).toBeInTheDocument();
    expect(screen.getByText("View Report")).toBeInTheDocument();
  });

  it("renders the split view when artifacts exist", () => {
    renderRoute({
      code: "<main.tf>\nresource {}\n</main.tf>",
      history: [{ role: "user", content: "deploy a VM" }],
    });

    expect(screen.getByLabelText("Follow-up question")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Report" })).toBeInTheDocument();
    expect(screen.getByText("View Report")).toBeInTheDocument();
  });

  // A session opened while its round is still running has no artifacts yet:
  // rendering the results view would show an empty, dead-end screen and never
  // notice the run finishing. The route hands it back to the live view.
  describe("still-running sessions", () => {
    beforeEach(() => {
      mockState.clear();
    });

    it("rejoins the live run instead of rendering an empty result", async () => {
      mockState.addSession(
        makeSessionDetail({
          current_status: "generating",
          in_flight: true,
          rounds: [
            makeRound({
              statuses: [makeStatus("started"), makeStatus("generating")],
            }),
          ],
        }),
      );

      // The sessions-table reload patches the running session in, then
      // navigates here.
      renderRoute({ current_status: "generating" });

      await waitFor(() =>
        expect(resume).toHaveBeenCalledWith({
          sessionId: "sess-1",
          isApply: false,
        }),
      );
      expect(screen.queryByLabelText("Follow-up question")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Report" })).not.toBeInTheDocument();
    });

    it("resumes a running apply round with the apply phase labels", async () => {
      mockState.addSession(
        makeSessionDetail({
          current_status: "apply",
          in_flight: true,
          rounds: [
            makeRound({
              statuses: [makeStatus("started"), makeStatus("apply")],
            }),
          ],
        }),
      );

      renderRoute({ current_status: "apply" });

      await waitFor(() =>
        expect(resume).toHaveBeenCalledWith({
          sessionId: "sess-1",
          isApply: true,
        }),
      );
    });

    it("resumes only once while the route stays mounted", async () => {
      mockState.addSession(
        makeSessionDetail({
          current_status: "generating",
          in_flight: true,
          rounds: [
            makeRound({
              statuses: [makeStatus("started"), makeStatus("generating")],
            }),
          ],
        }),
      );

      renderRoute({ current_status: "generating" });

      await waitFor(() => expect(resume).toHaveBeenCalled());
      expect(resume).toHaveBeenCalledTimes(1);
    });
  });

});
