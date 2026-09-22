// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * The only default handlers the suite relies on: the /api/v1/sessions
 * list and detail pair, served out of `mockState`. Anything else a test
 * needs, it registers itself with `server.use(...)` — there are ~54 such
 * overrides across the suite, which is the intended pattern.
 */

import { http, HttpResponse } from "msw";
import { mockState } from "./factories";
import type {
  PaginatedSessionSummary,
  SessionDetail,
  SessionSummary,
} from "@/types/api";

export function toSummary(detail: SessionDetail): SessionSummary {
  return {
    uuid: detail.uuid,
    username: detail.username,
    operation: detail.operation,
    provider: detail.provider,
    first_query: detail.first_query,
    workspace_uri: detail.workspace_uri,
    current_status: detail.current_status,
    in_flight: detail.in_flight,
    is_blocked: detail.is_blocked,
    created_at: detail.created_at,
    updated_at: detail.updated_at,
  };
}

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
  items: SessionDetail[],
  query: ListQuery,
): SessionSummary[] {
  const needle = query.search.toLowerCase();
  return items
    .filter((s) => !query.status || s.current_status === query.status)
    .filter((s) => !query.operation || s.operation === query.operation)
    .filter(
      (s) =>
        !query.userEmail ||
        (s.username ?? "")
          .toLowerCase()
          .includes(query.userEmail.toLowerCase()),
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
    return HttpResponse.json(
      paginate(filterSessions(sortedSessions(), query), query),
    );
  }),

  http.get("/api/v1/sessions/:sessionId", ({ params, request }) => {
    const detail = mockState.getSession(params.sessionId as string);
    if (!detail) {
      return HttpResponse.json(
        { detail: "Session not found" },
        { status: 404 },
      );
    }
    return HttpResponse.json(projectDetail(detail, request));
  }),
];
