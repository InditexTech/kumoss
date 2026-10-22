// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { makeSessionDetail, mockState } from "@/test/factories";
import { readListQuery, filterSessions, paginate, sortedSessions } from "@/test/handlers";
import { renderWithProviders } from "@/test/render";
import type { PanelRole } from "@/types/api";
import SessionsPage from "./SessionsPage";

const auth = vi.hoisted(() => ({
  panelRole: "viewer" as PanelRole | null,
  hasPanelAccess: true,
  isPanelAdmin: false,
}));
vi.mock("@/contexts/AuthContext", () => ({ useAuth: () => auth }));

function renderPage(variant: "admin" | "user", path: string) {
  return renderWithProviders(<SessionsPage variant={variant} />, {
    withNotifications: true,
    routerProps: { initialEntries: [path] },
  });
}

describe("Filter sync between search inputs and dropdown filters", () => {
  beforeEach(() => {
    mockState.clear();
    mockState.addSession(
      makeSessionDetail({
        uuid: "s1",
        operation: "generate",
        current_status: "completed",
        first_query: "Deploy Azure VM",
        username: "alice@example.com",
        created_at: "2026-01-03T00:00:00Z",
      }),
    );
    mockState.addSession(
      makeSessionDetail({
        uuid: "s2",
        operation: "drift",
        current_status: "failed",
        first_query: "Drift detection",
        username: "bob@example.com",
        created_at: "2026-01-02T00:00:00Z",
      }),
    );
    mockState.addSession(
      makeSessionDetail({
        uuid: "s3",
        operation: "generate",
        current_status: "failed",
        first_query: "Failed deploy",
        username: "alice@example.com",
        created_at: "2026-01-01T00:00:00Z",
      }),
    );
  });

  it("flushes pending search text when a dropdown filter is selected", async () => {
    const capturedQueries: string[] = [];
    server.use(
      http.get("/api/v1/sessions/list", ({ request }) => {
        capturedQueries.push(new URL(request.url).search);
        const query = readListQuery(request);
        return HttpResponse.json(
          paginate(filterSessions(sortedSessions(), query), query),
        );
      }),
    );

    auth.panelRole = null;
    renderPage("user", "/user/sessions");

    // Wait for initial load
    await screen.findByText("Deploy Azure VM");
    const initialCallCount = capturedQueries.length;

    // Type search text but DON'T press Enter
    const searchInput = screen.getByPlaceholderText(
      "Search by project name, query or session id",
    );
    await userEvent.type(searchInput, "Deploy");

    // Now select a dropdown filter
    await userEvent.click(screen.getByText("STATUS"));
    await userEvent.click(await screen.findByRole("option", { name: "Completed" }));

    // Wait for the reload triggered by the dropdown
    await waitFor(() => {
      expect(capturedQueries.length).toBeGreaterThan(initialCallCount);
    });

    // The LAST API call should include BOTH the search text AND the status filter
    const lastQuery = capturedQueries[capturedQueries.length - 1];
    expect(lastQuery).toContain("status=completed");
    expect(lastQuery).toContain("search=Deploy");
  });

  it("flushes pending search text when changing page", async () => {
    const capturedQueries: string[] = [];
    server.use(
      http.get("/api/v1/sessions/list", ({ request }) => {
        capturedQueries.push(new URL(request.url).search);
        const query = readListQuery(request);
        return HttpResponse.json(
          paginate(filterSessions(sortedSessions(), query), query),
        );
      }),
    );

    auth.panelRole = null;
    renderPage("user", "/user/sessions?pageSize=1");

    await screen.findByText("Deploy Azure VM");
    const initialCallCount = capturedQueries.length;

    const searchInput = screen.getByPlaceholderText(
      "Search by project name, query or session id",
    );
    await userEvent.type(searchInput, "Deploy");

    // Click next-page without pressing Enter on search
    const nextButton = screen.getByTestId("NavigateNextIcon").closest("button")!;
    await userEvent.click(nextButton);

    await waitFor(() => {
      expect(capturedQueries.length).toBeGreaterThan(initialCallCount);
    });

    const lastQuery = capturedQueries[capturedQueries.length - 1];
    expect(lastQuery).toContain("search=Deploy");
  });

  it("flushes pending search text when changing page size", async () => {
    const capturedQueries: string[] = [];
    server.use(
      http.get("/api/v1/sessions/list", ({ request }) => {
        capturedQueries.push(new URL(request.url).search);
        const query = readListQuery(request);
        return HttpResponse.json(
          paginate(filterSessions(sortedSessions(), query), query),
        );
      }),
    );

    auth.panelRole = null;
    renderPage("user", "/user/sessions");

    await screen.findByText("Deploy Azure VM");
    const initialCallCount = capturedQueries.length;

    const searchInput = screen.getByPlaceholderText(
      "Search by project name, query or session id",
    );
    await userEvent.type(searchInput, "Deploy");

    // Change page size without pressing Enter on search
    const pageSizeSelect = document.getElementById("mui-component-select-page-size")!;
    await userEvent.click(pageSizeSelect);
    await userEvent.click(await screen.findByRole("option", { name: "25" }));

    await waitFor(() => {
      expect(capturedQueries.length).toBeGreaterThan(initialCallCount);
    });

    const lastQuery = capturedQueries[capturedQueries.length - 1];
    expect(lastQuery).toContain("search=Deploy");
    expect(lastQuery).toContain("page_size=25");
  });

  it("flushes admin user email when a dropdown filter is selected", async () => {
    const capturedQueries: string[] = [];
    server.use(
      http.get("/api/v1/admin/sessions/list", ({ request }) => {
        capturedQueries.push(new URL(request.url).search);
        const query = readListQuery(request);
        return HttpResponse.json(
          paginate(filterSessions(sortedSessions(), query), query),
        );
      }),
    );

    auth.panelRole = "viewer";
    renderPage("admin", "/admin");

    await screen.findByText("Deploy Azure VM");
    const initialCallCount = capturedQueries.length;

    // Type user email but DON'T press Enter
    const emailInput = screen.getByPlaceholderText("Search by user email");
    await userEvent.type(emailInput, "alice");

    // Select a dropdown filter
    await userEvent.click(screen.getByText("TYPE"));
    await userEvent.click(await screen.findByRole("option", { name: "Generate" }));

    await waitFor(() => {
      expect(capturedQueries.length).toBeGreaterThan(initialCallCount);
    });

    const lastQuery = capturedQueries[capturedQueries.length - 1];
    expect(lastQuery).toContain("operation=generate");
    expect(lastQuery).toContain("user_email=alice");
  });
});
