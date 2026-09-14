// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { Routes, Route, Outlet } from "react-router-dom";
import React, { useEffect, useState } from "react";
import { useSession } from "@/contexts/SessionContext";
import { renderWithProviders } from "@/test/render";
import {
  mockState,
  makeSessionDetail,
  makeRound,
  makeStatus,
} from "@/mocks/state";
import ApplyResultsRoute from "./ApplyResultsRoute";

const iterate = vi.fn();
const applyAfterPr = vi.fn();
const resume = vi.fn();

function LayoutStub() {
  const context = {
    view: "apply-results" as const,
    isSplitView: true,
    handleContactTeam: vi.fn(),
    wizard: { iterate, applyAfterPr, resume },
  };
  return <Outlet context={context} />;
}

/** Applies the session patch BEFORE mounting the route, mirroring the
 *  context the sessions table / wizard leave behind. */
function SessionGate({ patch, children }: {
  patch: Record<string, unknown>;
  children: React.ReactNode;
}) {
  const { updateSession } = useSession();
  const [ready, setReady] = useState(false);
  useEffect(() => {
    updateSession(patch);
    setReady(true);
  }, []);
  return ready ? <>{children}</> : null;
}

function renderRoute(sessionPatch: Record<string, unknown>) {
  return renderWithProviders(
    <SessionGate patch={{ uuid: "sess-1", ...sessionPatch }}>
      <Routes>
        <Route element={<LayoutStub />}>
          <Route
            path="/home/apply-results/:sessionId"
            element={<ApplyResultsRoute />}
          />
        </Route>
      </Routes>
    </SessionGate>,
    {
      withNotifications: true,
      routerProps: { initialEntries: ["/home/apply-results/sess-1"] },
    },
  );
}

describe("ApplyResultsRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockState.clear();
  });

  // An apply writes its artifacts only once it ends, so reopening a running
  // apply used to land on "No apply results available." with nothing left to
  // wait for.
  it("rejoins a running apply instead of rendering an empty result", async () => {
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
    expect(
      screen.queryByText("No apply results available."),
    ).not.toBeInTheDocument();
  });

  it("renders the apply results of a finished round without resuming", async () => {
    renderRoute({
      current_status: "completed",
      applyResults: {
        sessionId: "sess-1",
        status: "success",
        message: "Apply complete",
        errorMessage: "",
        timestamp: "2026-01-01T00:00:00Z",
      },
    });

    expect(await screen.findByText(/Execution Summary/)).toBeInTheDocument();
    expect(resume).not.toHaveBeenCalled();
  });
});
