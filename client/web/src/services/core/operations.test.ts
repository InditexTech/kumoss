// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { cancelOperation, getOperation, listOperations } from "./operations";
import { listSchedules } from "./schedules";

describe("operations client", () => {
  it("lists with only the set filters", async () => {
    let query = "";
    server.use(
      http.get("/api/v1/operations", ({ request }) => {
        query = new URL(request.url).search;
        return HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 });
      }),
    );
    await listOperations({ session_id: "sess-1", status: "pending", kind: undefined });
    expect(query).toBe("?session_id=sess-1&status=pending");
    await listOperations();
    expect(query).toBe("");
  });

  it("gets and cancels an operation by id", async () => {
    const seen: string[] = [];
    server.use(
      http.get("/api/v1/operations/:id", ({ params }) => {
        seen.push(`get ${String(params.id)}`);
        return HttpResponse.json({ uuid: params.id, status: "running" });
      }),
      http.post("/api/v1/operations/:id/cancel", ({ params }) => {
        seen.push(`cancel ${String(params.id)}`);
        return HttpResponse.json({ status: "cancelled" }, { status: 202 });
      }),
    );
    expect((await getOperation("op 1")).status).toBe("running");
    expect((await cancelOperation("op 1")).status).toBe("cancelled");
    expect(seen).toEqual(["get op 1", "cancel op 1"]);
  });
});

describe("schedules client", () => {
  it("lists without a query string when no params are set", async () => {
    let search = "unset";
    server.use(
      http.get("/api/v1/schedules", ({ request }) => {
        search = new URL(request.url).search;
        return HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 });
      }),
    );
    await listSchedules();
    expect(search).toBe("");
  });
});
