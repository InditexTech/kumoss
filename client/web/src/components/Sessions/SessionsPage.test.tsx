// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/mocks/server";
import { makeSessionDetail, mockState } from "@/mocks/state";
import { renderWithProviders } from "@/test/render";
import type { PanelRole, SessionDetail } from "@/types/api";
import SessionsPage from "./SessionsPage";

const auth = vi.hoisted(() => ({ panelRole: null as PanelRole | null }));
vi.mock("@/contexts/AuthContext", () => ({ useAuth: () => auth }));

function paginated(items: SessionDetail[]) {
  return { items, total: items.length, page: 1, page_size: 10, total_pages: 1 };
}

function mockAdminSession(detail: SessionDetail) {
  const patches: Array<{ allowed: boolean }> = [];
  server.use(
    http.get("/api/v1/admin/sessions", () =>
      HttpResponse.json(paginated([detail])),
    ),
    http.get("/api/v1/admin/sessions/:id", () => HttpResponse.json(detail)),
    http.patch(
      "/api/v1/admin/sessions/:id/apply_allowed",
      async ({ request }) => {
        const body = (await request.json()) as { allowed: boolean };
        patches.push(body);
        return HttpResponse.json({
          uuid: detail.uuid,
          apply_allowed: body.allowed,
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

    await waitFor(() => expect(patches).toEqual([{ allowed: true }]));
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
