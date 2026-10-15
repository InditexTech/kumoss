// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, beforeEach } from "vitest";
import {
  toSummary,
  readListQuery,
  filterSessions,
  paginate,
  sortedSessions,
  projectDetail,
  projectAdminDetail,
  type ListQuery,
} from "./handlers";
import { makeSessionDetail, mockState } from "./factories";
import type { AdminSessionDetail, SessionSummary } from "@/types/api";

function makeRequest(path: string): Request {
  return new Request(`http://localhost${path}`);
}

function defaultQuery(overrides: Partial<ListQuery> = {}): ListQuery {
  return {
    page: 1,
    pageSize: 20,
    search: "",
    status: "",
    operation: "",
    userEmail: "",
    ...overrides,
  };
}

describe("toSummary", () => {
  it("projects a SessionDetail down to SessionSummary keys", () => {
    const detail = makeSessionDetail();
    const summary = toSummary(detail);
    const keys = Object.keys(summary).sort();
    expect(keys).toEqual([
      "created_at",
      "current_status",
      "first_query",
      "in_flight",
      "is_blocked",
      "operation",
      "provider",
      "updated_at",
      "username",
      "uuid",
      "workspace",
    ]);
    expect(summary.uuid).toBe(detail.uuid);
    expect(summary.workspace).toBe(detail.workspace);
  });

  it("does not carry rounds, scope_id, or chat_history", () => {
    const summary = toSummary(makeSessionDetail()) as Record<string, unknown>;
    expect(summary).not.toHaveProperty("rounds");
    expect(summary).not.toHaveProperty("scope_id");
    expect(summary).not.toHaveProperty("chat_history");
  });
});

describe("readListQuery", () => {
  it("extracts defaults from an empty query string", () => {
    const q = readListQuery(makeRequest("/api/v1/sessions/list"));
    expect(q).toEqual(defaultQuery());
  });

  it("reads every supported parameter", () => {
    const q = readListQuery(
      makeRequest(
        "/api/v1/sessions/list?page=3&page_size=5&search=vm&status=completed&operation=drift&user_email=alice",
      ),
    );
    expect(q).toEqual({
      page: 3,
      pageSize: 5,
      search: "vm",
      status: "completed",
      operation: "drift",
      userEmail: "alice",
    });
  });
});

describe("filterSessions", () => {
  const sessions: AdminSessionDetail[] = [
    makeSessionDetail({
      uuid: "s1",
      username: "alice@test.com",
      current_status: "completed",
      operation: "generate",
      first_query: "deploy a VM",
    }),
    makeSessionDetail({
      uuid: "s2",
      username: "bob@test.com",
      current_status: "failed",
      operation: "drift",
      first_query: "check drift",
    }),
    makeSessionDetail({
      uuid: "s3",
      username: "carol@test.com",
      current_status: "completed",
      operation: "generate",
      first_query: "create a bucket",
    }),
  ];

  it("returns all as summaries when no filters set", () => {
    const result = filterSessions(sessions, defaultQuery());
    expect(result).toHaveLength(3);
  });

  it("filters by status", () => {
    const result = filterSessions(
      sessions,
      defaultQuery({ status: "failed" }),
    );
    expect(result).toHaveLength(1);
    expect(result[0].uuid).toBe("s2");
  });

  it("filters by operation", () => {
    const result = filterSessions(
      sessions,
      defaultQuery({ operation: "drift" }),
    );
    expect(result).toHaveLength(1);
    expect(result[0].uuid).toBe("s2");
  });

  it("filters by userEmail (partial, case-insensitive)", () => {
    const result = filterSessions(
      sessions,
      defaultQuery({ userEmail: "ALICE" }),
    );
    expect(result).toHaveLength(1);
    expect(result[0].uuid).toBe("s1");
  });

  it("filters by search across username, first_query, and workspace uri", () => {
    const result = filterSessions(
      sessions,
      defaultQuery({ search: "bucket" }),
    );
    expect(result).toHaveLength(1);
    expect(result[0].uuid).toBe("s3");
  });

  it("applies multiple filters together", () => {
    const result = filterSessions(
      sessions,
      defaultQuery({ status: "completed", operation: "generate", search: "VM" }),
    );
    expect(result).toHaveLength(1);
    expect(result[0].uuid).toBe("s1");
  });

  it("returns empty when nothing matches", () => {
    const result = filterSessions(
      sessions,
      defaultQuery({ status: "validating" }),
    );
    expect(result).toHaveLength(0);
  });
});

describe("paginate", () => {
  const items: SessionSummary[] = Array.from({ length: 5 }, (_, i) =>
    toSummary(makeSessionDetail({ uuid: `p${i}` })),
  );

  it("returns the first page", () => {
    const result = paginate(items, defaultQuery({ pageSize: 2 }));
    expect(result.items).toHaveLength(2);
    expect(result.total).toBe(5);
    expect(result.page).toBe(1);
    expect(result.page_size).toBe(2);
    expect(result.total_pages).toBe(3);
  });

  it("returns a middle page", () => {
    const result = paginate(items, defaultQuery({ page: 2, pageSize: 2 }));
    expect(result.items).toHaveLength(2);
    expect(result.items[0].uuid).toBe("p2");
  });

  it("returns a partial last page", () => {
    const result = paginate(items, defaultQuery({ page: 3, pageSize: 2 }));
    expect(result.items).toHaveLength(1);
  });

  it("returns empty items and zero total_pages for empty list", () => {
    const result = paginate([], defaultQuery());
    expect(result.items).toEqual([]);
    expect(result.total).toBe(0);
    expect(result.total_pages).toBe(0);
  });
});

describe("sortedSessions", () => {
  beforeEach(() => mockState.clear());

  it("returns sessions newest-first", () => {
    mockState.addSession(
      makeSessionDetail({ uuid: "old", created_at: "2026-01-01T00:00:00Z" }),
    );
    mockState.addSession(
      makeSessionDetail({ uuid: "new", created_at: "2026-06-01T00:00:00Z" }),
    );
    const sorted = sortedSessions();
    expect(sorted[0].uuid).toBe("new");
    expect(sorted[1].uuid).toBe("old");
  });
});

describe("projectDetail", () => {
  const detail = makeSessionDetail({
    chat_history: [{ user: "hi", assistant: "hello" }],
    history: [{ user: "hi", assistant: "<raw>" }],
  });

  it("drops chat_history when include_chat_history is not set", () => {
    const result = projectDetail(detail, makeRequest("/api/v1/sessions?id=sess-1"));
    expect(result.chat_history).toBeNull();
  });

  it("includes chat_history when flag is true", () => {
    const result = projectDetail(
      detail,
      makeRequest("/api/v1/sessions?id=sess-1&include_chat_history=true"),
    );
    expect(result.chat_history).toEqual([{ user: "hi", assistant: "hello" }]);
  });

  it("always drops history (admin-only field)", () => {
    const result = projectDetail(
      detail,
      makeRequest("/api/v1/sessions?id=sess-1&include_chat_history=true"),
    ) as Record<string, unknown>;
    expect(result).not.toHaveProperty("history");
  });
});

describe("projectAdminDetail", () => {
  const detail = makeSessionDetail({
    chat_history: [{ user: "hi", assistant: "hello" }],
    history: [{ user: "hi", assistant: "<raw>" }],
  });

  it("drops both records by default", () => {
    const result = projectAdminDetail(detail, makeRequest("/api/v1/admin/sessions?id=sess-1"));
    expect(result.chat_history).toBeNull();
    expect(result.history).toBeNull();
  });

  it("includes both when their flags are set", () => {
    const result = projectAdminDetail(
      detail,
      makeRequest(
        "/api/v1/admin/sessions?id=sess-1&include_chat_history=true&include_history=true",
      ),
    );
    expect(result.chat_history).toEqual([{ user: "hi", assistant: "hello" }]);
    expect(result.history).toEqual([{ user: "hi", assistant: "<raw>" }]);
  });

  it("can include history without chat_history", () => {
    const result = projectAdminDetail(
      detail,
      makeRequest("/api/v1/admin/sessions?id=sess-1&include_history=true"),
    );
    expect(result.chat_history).toBeNull();
    expect(result.history).toEqual([{ user: "hi", assistant: "<raw>" }]);
  });
});
