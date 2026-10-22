// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useLocation } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { makeSessionDetail, mockState } from "@/test/factories";
import { projectAdminDetail } from "@/test/handlers";
import { renderWithProviders } from "@/test/render";
import {
  resolveSessionOutcome,
  buildSessionPatch,
  buildApplyResults,
  findSessionPr,
} from "@/services/workflows/session_outcome";
import type { AdminSessionDetail, PanelRole } from "@/types/api";
import SessionsPage from "./SessionsPage";

vi.mock("@/services/workflows/session_outcome", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/workflows/session_outcome")>();
  return {
    ...actual,
    resolveSessionOutcome: vi.fn(),
    buildSessionPatch: vi.fn(),
    buildApplyResults: vi.fn(),
    findSessionPr: vi.fn(),
  };
});

vi.mock("@/services/core/sessionsCache", () => ({
  getCachedSessions: vi.fn(),
  setCachedSessions: vi.fn(),
  invalidateSessionsCache: vi.fn(),
}));

const auth = vi.hoisted(() => ({ panelRole: null as PanelRole | null }));
vi.mock("@/contexts/AuthContext", () => ({ useAuth: () => auth }));

function paginated(items: AdminSessionDetail[]) {
  return { items, total: items.length, page: 1, page_size: 10, total_pages: 1 };
}

function mockAdminSession(detail: AdminSessionDetail) {
  const patches: Array<{ locked: boolean }> = [];
  server.use(
    http.get("/api/v1/admin/sessions/list", () =>
      HttpResponse.json(paginated([detail])),
    ),
    // Projected like the real route, so each record only arrives when the
    // page actually asks for it.
    http.get("/api/v1/admin/sessions", ({ request }) =>
      HttpResponse.json(projectAdminDetail(detail, request)),
    ),
    http.patch(
      "/api/v1/admin/sessions/:id/toggle_lock",
      async ({ request }) => {
        const body = (await request.json()) as { locked: boolean };
        patches.push(body);
        return HttpResponse.json({
          uuid: detail.uuid,
          is_blocked: body.locked,
        });
      },
    ),
  );
  return patches;
}

function renderPage(variant: "admin" | "user", path: string) {
  return renderWithProviders(<SessionsPage variant={variant} />, {
    withNotifications: true,
    routerProps: { initialEntries: [path] },
  });
}

function LocationProbe() {
  const { pathname } = useLocation();
  return <div data-testid="location">{pathname}</div>;
}

function renderPageWithProbe(variant: "admin" | "user", path: string) {
  return renderWithProviders(
    <>
      <LocationProbe />
      <SessionsPage variant={variant} />
    </>,
    { withNotifications: true, routerProps: { initialEntries: [path] } },
  );
}

describe("SessionsPage session id column", () => {
  const uuid = "9b2e4c1a-7d3f-4e55-a1b2-c3d4e5f60789";

  beforeEach(() => {
    mockState.clear();
  });

  it("shows a shortened id with the full uuid on hover in the admin table", async () => {
    auth.panelRole = "viewer";
    mockAdminSession(makeSessionDetail({ uuid }));
    renderPage("admin", "/admin");

    const cell = await screen.findByTitle(uuid);
    expect(cell).toHaveTextContent("9b2e4c1a");
    expect(screen.getByRole("columnheader", { name: "Session ID" })).toBeInTheDocument();
  });

  it("has no id column in the user's own sessions view", async () => {
    auth.panelRole = null;
    mockState.addSession(makeSessionDetail({ uuid }));
    renderPage("user", "/user/sessions");

    await screen.findByText("deploy a VM");
    expect(screen.queryByRole("columnheader", { name: "Session ID" })).toBeNull();
    expect(screen.queryByTitle(uuid)).toBeNull();
  });
});

describe("SessionsPage apply lock in the table", () => {
  beforeEach(() => {
    mockState.clear();
  });

  it("offers the lock toggle for drift sessions in the admin view", async () => {
    auth.panelRole = "editor";
    mockAdminSession(makeSessionDetail({ operation: "drift", is_blocked: false }));
    renderPage("admin", "/admin");

    expect(
      await screen.findByRole("button", { name: "Lock apply" }),
    ).toBeInTheDocument();
  });

  it("shows the lock state for drift sessions in the user view", async () => {
    auth.panelRole = null;
    mockState.addSession(makeSessionDetail({ operation: "drift", is_blocked: true }));
    renderPage("user", "/user/sessions");

    expect(await screen.findByTestId("LockOutlinedIcon")).toBeInTheDocument();
  });
});

describe("SessionsPage apply lock in the detail panel", () => {
  beforeEach(() => {
    mockState.clear();
  });

  it("lets a panel editor toggle the lock from the detail button", async () => {
    auth.panelRole = "editor";
    const patches = mockAdminSession(makeSessionDetail({ is_blocked: true }));
    renderPage("admin", "/admin?session=sess-1");

    await userEvent.click(
      await screen.findByRole("button", { name: /apply locked/i }),
    );

    await waitFor(() => expect(patches).toEqual([{ locked: false }]));
    expect(
      await screen.findByRole("button", { name: /apply open/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Lock apply" })).toBeInTheDocument();
  });

  it("keeps the label read-only for a panel viewer", async () => {
    auth.panelRole = "viewer";
    mockAdminSession(makeSessionDetail({ is_blocked: true }));
    renderPage("admin", "/admin?session=sess-1");

    expect(await screen.findByText("Apply Locked")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /apply locked/i })).toBeNull();
  });

  it("keeps the label read-only on the user's own sessions view", async () => {
    auth.panelRole = "admin";
    mockState.addSession(makeSessionDetail({ is_blocked: true }));
    renderPage("user", "/user/sessions?session=sess-1");

    expect(await screen.findByText("Apply Locked")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /apply locked/i })).toBeNull();
  });
});

describe("SessionsPage handleReload", () => {
  const mockResolve = vi.mocked(resolveSessionOutcome);
  const mockPatch = vi.mocked(buildSessionPatch);
  const mockApply = vi.mocked(buildApplyResults);
  const mockFindPr = vi.mocked(findSessionPr);

  beforeEach(() => {
    mockState.clear();
    vi.clearAllMocks();
  });

  it("navigates to the results page on a successful reload", async () => {
    auth.panelRole = null;
    const detail = makeSessionDetail({ uuid: "sess-1", current_status: "completed" });
    mockState.addSession(detail);

    mockResolve.mockResolvedValue({
      kind: "results",
      detail,
      round: detail.rounds[0],
      report: null,
      compliance: null,
      code: "",
    });
    mockPatch.mockReturnValue({ uuid: "sess-1" });
    mockFindPr.mockReturnValue({ number: 42, url: "https://git.example.com/pr/42" });

    renderPageWithProbe("user", "/user/sessions?session=sess-1");

    await userEvent.click(await screen.findByText("Reload Session"));

    await waitFor(() => {
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/home/results/sess-1",
      );
    });
    expect(mockResolve).toHaveBeenCalled();
    expect(mockPatch).toHaveBeenCalled();
    expect(mockFindPr).toHaveBeenCalled();
    expect(mockApply).not.toHaveBeenCalled();
  });

  it("navigates to the apply-results page for an apply outcome", async () => {
    auth.panelRole = null;
    const detail = makeSessionDetail({ uuid: "sess-1", current_status: "completed" });
    mockState.addSession(detail);

    mockResolve.mockResolvedValue({
      kind: "apply-results",
      detail,
      round: detail.rounds[0],
      report: null,
    });
    mockPatch.mockReturnValue({ uuid: "sess-1" });
    mockApply.mockReturnValue({
      sessionId: "sess-1",
      status: "Succeeded",
      message: "",
      errorMessage: "",
      timestamp: detail.updated_at,
      applyReport: null,
    });
    mockFindPr.mockReturnValue(null);

    renderPageWithProbe("user", "/user/sessions?session=sess-1");

    await userEvent.click(await screen.findByText("Reload Session"));

    await waitFor(() => {
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/home/apply-results/sess-1",
      );
    });
    expect(mockApply).toHaveBeenCalled();
  });
});

describe("SessionsPage search prefill from URL", () => {
  beforeEach(() => {
    mockState.clear();
  });

  it("pre-fills the search input from URL params on mount", async () => {
    auth.panelRole = null;
    mockState.addSession(makeSessionDetail());
    renderPage("user", "/user/sessions?search=VM");

    const input = await screen.findByPlaceholderText(
      "Search by project name, query or session id",
    );
    expect(input).toHaveValue("VM");
  });
});
