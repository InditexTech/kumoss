// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { http, HttpResponse } from "msw";
import { MOCK_USER_EMAIL, MOCK_USERS, toSummary } from "../data";
import { mockState } from "../state";
import type {
  PaginatedSessionSummary,
  SessionDetail,
  SessionSummary,
} from "@/types/api";

/** Seeded users other than the caller; their sessions never show in /sessions. */
const OTHER_USERS = MOCK_USERS.map((u) => u.email).filter(
  (email): email is string => !!email && email !== MOCK_USER_EMAIL,
);

export interface ListQuery {
  page: number;
  pageSize: number;
  search: string;
  status: string;
  operation: string;
  userEmail: string;
}

export function readListQuery(request: Request): ListQuery {
  const url = new URL(request.url);
  return {
    page: Number(url.searchParams.get("page") ?? "1"),
    pageSize: Number(url.searchParams.get("page_size") ?? "20"),
    search: url.searchParams.get("search") ?? "",
    status: url.searchParams.get("status") ?? "",
    operation: url.searchParams.get("operation") ?? "",
    userEmail: url.searchParams.get("user_email") ?? "",
  };
}

/** `search` is a partial match over the same columns the backend indexes. */
export function filterSessions(
  sessions: SessionDetail[],
  query: ListQuery,
): SessionSummary[] {
  const needle = query.search.toLowerCase();
  return sessions
    .filter((s) => !query.status || s.current_status === query.status)
    .filter((s) => !query.operation || s.operation === query.operation)
    .filter(
      (s) =>
        !query.userEmail ||
        (s.username ?? "").toLowerCase().includes(query.userEmail.toLowerCase()),
    )
    .filter(
      (s) =>
        !needle ||
        (s.username ?? "").toLowerCase().includes(needle) ||
        (s.first_query ?? "").toLowerCase().includes(needle) ||
        s.workspace_uri.toLowerCase().includes(needle),
    )
    .map(toSummary);
}

export function paginate(
  items: SessionSummary[],
  query: ListQuery,
): PaginatedSessionSummary {
  const start = (query.page - 1) * query.pageSize;
  return {
    items: items.slice(start, start + query.pageSize),
    total: items.length,
    page: query.page,
    page_size: query.pageSize,
    total_pages: items.length ? Math.ceil(items.length / query.pageSize) : 0,
  };
}

/** Newest first, as the backend orders both list endpoints. */
export function sortedSessions(): SessionDetail[] {
  return [...mockState.listSessions()].sort((a, b) =>
    b.created_at.localeCompare(a.created_at),
  );
}

/** `history` is only serialized when explicitly requested. */
export function projectDetail(
  detail: SessionDetail,
  request: Request,
): SessionDetail {
  const includeHistory =
    new URL(request.url).searchParams.get("include_history") === "true";
  return includeHistory ? detail : { ...detail, history: null };
}

export const sessionHandlers = [
  http.get("/api/v1/sessions", ({ request }) => {
    const query = readListQuery(request);
    const own = sortedSessions().filter(
      (s) => !s.username || !OTHER_USERS.includes(s.username),
    );
    return HttpResponse.json(paginate(filterSessions(own, query), query));
  }),

  http.get("/api/v1/sessions/:sessionId", ({ params, request }) => {
    const detail = mockState.getSession(params.sessionId as string);
    if (!detail) {
      return HttpResponse.json({ detail: "Session not found" }, { status: 404 });
    }
    return HttpResponse.json(projectDetail(detail, request));
  }),
];
