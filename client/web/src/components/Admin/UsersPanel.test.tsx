// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi } from "vitest";
import { screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithProviders } from "@/test/render";
import type { AdminUserEntry, UpdateUserRolesRequest } from "@/types/api";
import UsersPanel from "./UsersPanel";

const me: AdminUserEntry = {
  id: 1,
  email: "admin@example.com",
  display_name: "Ada Admin",
  operation_role: "devops",
  panel_role: "admin",
  issuer: "urn:test",
  subject: "sub-1",
  created_at: "2026-01-01T00:00:00Z",
};

const bob: AdminUserEntry = {
  id: 2,
  email: "bob@example.com",
  display_name: "Bob Stone",
  operation_role: "developer",
  panel_role: "viewer",
  issuer: "urn:test",
  subject: "sub-2",
  created_at: "2026-01-02T00:00:00Z",
};

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({
    user: {
      id: 1,
      email: "admin@example.com",
      displayName: "Ada Admin",
      operationRole: "devops",
      panelRole: "admin",
    },
  }),
}));

function mockUsers() {
  const puts: Array<{ id: number; body: UpdateUserRolesRequest }> = [];
  server.use(
    http.get("/api/v1/admin/users", () =>
      HttpResponse.json({
        items: [me, bob],
        total: 2,
        page: 1,
        page_size: 10,
        total_pages: 1,
      }),
    ),
    http.put("/api/v1/admin/users/:id/roles", async ({ params, request }) => {
      const body = (await request.json()) as UpdateUserRolesRequest;
      const id = Number(params.id);
      puts.push({ id, body });
      const base = id === me.id ? me : bob;
      return HttpResponse.json({ ...base, ...body });
    }),
  );
  return puts;
}

async function rowFor(name: string) {
  const cell = await screen.findByText(name);
  const row = cell.closest("tr");
  if (!row) throw new Error(`no row for ${name}`);
  return row;
}

describe("UsersPanel role management", () => {
  it("sends the full role state on each change and reflects the update", async () => {
    const puts = mockUsers();
    renderWithProviders(<UsersPanel />, { withNotifications: true });

    const bobRow = await rowFor("Bob Stone");
    const [operationSelect, panelSelect] = within(bobRow).getAllByRole("combobox");
    expect(operationSelect).toHaveTextContent("Developer");
    expect(panelSelect).toHaveTextContent("Viewer");

    await userEvent.click(operationSelect);
    await userEvent.click(await screen.findByRole("option", { name: "DevOps" }));
    await waitFor(() =>
      expect(puts).toEqual([
        { id: 2, body: { operation_role: "devops", panel_role: "viewer" } },
      ]),
    );
    await waitFor(() => expect(operationSelect).toHaveTextContent("DevOps"));

    await userEvent.click(panelSelect);
    await userEvent.click(await screen.findByRole("option", { name: "No access" }));
    await waitFor(() =>
      expect(puts[1]).toEqual({
        id: 2,
        body: { operation_role: "devops", panel_role: null },
      }),
    );
    await waitFor(() => expect(panelSelect).toHaveTextContent("No access"));
  });

  it("disables only the current admin's panel-role select", async () => {
    mockUsers();
    renderWithProviders(<UsersPanel />, { withNotifications: true });

    const meRow = await rowFor("Ada Admin");
    const [operationSelect, panelSelect] = within(meRow).getAllByRole("combobox");
    expect(panelSelect).toHaveAttribute("aria-disabled", "true");
    expect(operationSelect).not.toHaveAttribute("aria-disabled", "true");

    const bobRow = await rowFor("Bob Stone");
    const [, bobPanelSelect] = within(bobRow).getAllByRole("combobox");
    expect(bobPanelSelect).not.toHaveAttribute("aria-disabled", "true");
  });
});
