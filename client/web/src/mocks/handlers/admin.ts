// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { http, HttpResponse, delay } from "msw";
import { MOCK_USERS } from "../data";
import { mockState } from "../state";
import {
  filterSessions,
  paginate,
  projectDetail,
  readListQuery,
  sortedSessions,
} from "./sessions";
import type {
  AdminUserEntry,
  PaginatedUsers,
  SessionLockResponse,
  UpdateUserRolesRequest,
} from "@/types/api";

/** Mutable copy: PUT /admin/users/{id}/roles has to stick for the session. */
const users: AdminUserEntry[] = MOCK_USERS.map((user) => ({ ...user }));

export const adminHandlers = [
  // Same DTO and filters as /sessions, minus the self-scoping.
  http.get("/api/v1/admin/sessions", async ({ request }) => {
    await delay(150);
    const query = readListQuery(request);
    return HttpResponse.json(
      paginate(filterSessions(sortedSessions(), query), query),
    );
  }),

  http.get("/api/v1/admin/sessions/:sessionId", async ({ params, request }) => {
    await delay(120);
    const detail = mockState.getSession(params.sessionId as string);
    if (!detail) {
      return HttpResponse.json({ detail: "Session not found" }, { status: 404 });
    }
    return HttpResponse.json(projectDetail(detail, request));
  }),

  // `locked` in, `is_blocked` out — the field is renamed at the boundary.
  http.patch(
    "/api/v1/admin/sessions/:sessionId/toggle_lock",
    async ({ params, request }) => {
      await delay(120);
      const uuid = params.sessionId as string;
      const detail = mockState.getSession(uuid);
      if (!detail) {
        return HttpResponse.json(
          { detail: "Session not found" },
          { status: 404 },
        );
      }
      const { locked } = (await request.json()) as { locked: boolean };
      detail.is_blocked = locked;
      const response: SessionLockResponse = { uuid, is_blocked: locked };
      return HttpResponse.json(response);
    },
  ),

  http.get("/api/v1/admin/users", async ({ request }) => {
    await delay(150);
    const url = new URL(request.url);
    const page = Number(url.searchParams.get("page") ?? "1");
    const pageSize = Number(url.searchParams.get("page_size") ?? "20");
    const search = (url.searchParams.get("search") ?? "").toLowerCase();

    const filtered = users.filter(
      (user) =>
        !search ||
        (user.email ?? "").toLowerCase().includes(search) ||
        (user.display_name ?? "").toLowerCase().includes(search),
    );
    const start = (page - 1) * pageSize;
    const response: PaginatedUsers = {
      items: filtered.slice(start, start + pageSize),
      total: filtered.length,
      page,
      page_size: pageSize,
      total_pages: filtered.length ? Math.ceil(filtered.length / pageSize) : 0,
    };
    return HttpResponse.json(response);
  }),

  // Full-state assignment: whatever is sent replaces both roles.
  http.put("/api/v1/admin/users/:userId/roles", async ({ params, request }) => {
    await delay(150);
    const userId = Number(params.userId);
    const user = users.find((u) => u.id === userId);
    if (!user) {
      return HttpResponse.json({ detail: "User not found" }, { status: 404 });
    }
    const body = (await request.json()) as UpdateUserRolesRequest;
    user.operation_role = body.operation_role;
    user.panel_role = body.panel_role;
    return HttpResponse.json(user);
  }),
];
