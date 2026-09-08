// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/mocks/server";
import { mockState } from "@/mocks/state";
import { subscribeToSession, checkSessionStatus } from "./events";
import { UNAUTHORIZED_EVENT } from "@/services/token";

const encoder = new TextEncoder();

beforeEach(() => {
  mockState.clear();
});

describe("subscribeToSession", () => {
  it("delivers SSE events via onmessage", async () => {
    server.use(
      http.get("/api/v1/events/subscribe/:sessionId", () => {
        const events = [
          { status_msg: "STARTED", detail: { validation_id: null, message: "Starting..." } },
          { status_msg: "GENERATING", detail: { validation_id: null, message: "Generating..." } },
          { status_msg: "COMPLETED", detail: { validation_id: null, message: "Done." } },
        ];
        const stream = new ReadableStream({
          start(controller) {
            for (const event of events) {
              controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
            }
            controller.close();
          },
        });
        return new HttpResponse(stream, {
          headers: { "Content-Type": "text/event-stream" },
        });
      }),
    );

    const received: unknown[] = [];
    const conn = subscribeToSession("test-session");
    conn.onmessage = (event) => {
      received.push(JSON.parse(event.data));
    };

    // Wait for stream to complete
    await vi.waitFor(() => {
      expect(received).toHaveLength(3);
    }, { timeout: 3000 });

    expect(received[0]).toMatchObject({ status_msg: "STARTED" });
    expect(received[1]).toMatchObject({ status_msg: "GENERATING" });
    expect(received[2]).toMatchObject({ status_msg: "COMPLETED" });

    conn.close();
  });

  it("calls onerror after all retries exhausted on non-OK response", async () => {
    server.use(
      http.get("/api/v1/events/subscribe/:sessionId", () => {
        return new HttpResponse(null, { status: 500 });
      }),
    );

    const onerror = vi.fn();
    const conn = subscribeToSession("bad-session", undefined, { retryBaseMs: 20 });
    conn.onerror = onerror;

    await vi.waitFor(() => {
      expect(onerror).toHaveBeenCalled();
    }, { timeout: 3000 });

    expect(onerror).toHaveBeenCalledTimes(1);
    conn.close();
  });

  it("signs out on 401 without retrying", async () => {
    let calls = 0;
    server.use(
      http.get("/api/v1/events/subscribe/:sessionId", () => {
        calls++;
        return new HttpResponse(null, { status: 401 });
      }),
    );
    const listener = vi.fn();
    window.addEventListener(UNAUTHORIZED_EVENT, listener);

    const onerror = vi.fn();
    const conn = subscribeToSession("expired", undefined, { retryBaseMs: 20 });
    conn.onerror = onerror;

    await vi.waitFor(() => {
      expect(onerror).toHaveBeenCalledTimes(1);
    }, { timeout: 3000 });
    await new Promise((resolve) => setTimeout(resolve, 100));

    expect(calls).toBe(1);
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(UNAUTHORIZED_EVENT, listener);
    conn.close();
  });

  it("retries on transient failure and delivers events on success", async () => {
    let callCount = 0;
    server.use(
      http.get("/api/v1/events/subscribe/:sessionId", () => {
        callCount++;
        if (callCount === 1) {
          return new HttpResponse(null, { status: 503 });
        }
        const stream = new ReadableStream({
          start(controller) {
            controller.enqueue(
              encoder.encode(`data: ${JSON.stringify({ status_msg: "COMPLETED", detail: { message: "Done." } })}\n\n`),
            );
            controller.close();
          },
        });
        return new HttpResponse(stream, {
          headers: { "Content-Type": "text/event-stream" },
        });
      }),
    );

    const received: unknown[] = [];
    const onerror = vi.fn();
    const conn = subscribeToSession("retry-session", undefined, { retryBaseMs: 20 });
    conn.onmessage = (event) => received.push(JSON.parse(event.data));
    conn.onerror = onerror;

    await vi.waitFor(() => {
      expect(received).toHaveLength(1);
    }, { timeout: 3000 });

    expect(onerror).not.toHaveBeenCalled();
    expect(callCount).toBeGreaterThanOrEqual(2);
    conn.close();
  });

  it("retries when the stream closes unexpectedly without abort", async () => {
    let callCount = 0;
    server.use(
      http.get("/api/v1/events/subscribe/:sessionId", () => {
        callCount++;
        const stream = new ReadableStream({
          start(controller) {
            if (callCount > 1) {
              controller.enqueue(
                encoder.encode(`data: ${JSON.stringify({ status_msg: "COMPLETED", detail: { message: "Done." } })}\n\n`),
              );
            }
            // First connection closes without delivering anything
            controller.close();
          },
        });
        return new HttpResponse(stream, {
          headers: { "Content-Type": "text/event-stream" },
        });
      }),
    );

    const received: unknown[] = [];
    const onerror = vi.fn();
    const conn = subscribeToSession("drop-session", undefined, { retryBaseMs: 20 });
    conn.onmessage = (event) => received.push(JSON.parse(event.data));
    conn.onerror = onerror;

    await vi.waitFor(() => {
      expect(received).toHaveLength(1);
    }, { timeout: 3000 });

    expect(onerror).not.toHaveBeenCalled();
    expect(callCount).toBeGreaterThanOrEqual(2);
    conn.close();
  });

  it("close() during retry delay aborts without calling onerror", async () => {
    server.use(
      http.get("/api/v1/events/subscribe/:sessionId", () => {
        return new HttpResponse(null, { status: 500 });
      }),
    );

    const onerror = vi.fn();
    const conn = subscribeToSession("abort-session");
    conn.onerror = onerror;

    // Close immediately — should abort during first retry delay
    await new Promise((r) => setTimeout(r, 50));
    conn.close();

    // Wait long enough for retries to have fired if close didn't work
    await new Promise((r) => setTimeout(r, 500));
    expect(onerror).not.toHaveBeenCalled();
  });

  it("close() aborts the connection", async () => {
    server.use(
      http.get("/api/v1/events/subscribe/:sessionId", () => {
        const stream = new ReadableStream({
          start(controller) {
            controller.enqueue(encoder.encode(`data: {"status_msg":"STARTED","detail":{"validation_id":null,"message":"Go"}}\n\n`));
            // Stream stays open — never close controller
          },
        });
        return new HttpResponse(stream, {
          headers: { "Content-Type": "text/event-stream" },
        });
      }),
    );

    const received: unknown[] = [];
    const conn = subscribeToSession("test-session");
    conn.onmessage = (event) => {
      received.push(JSON.parse(event.data));
    };

    await vi.waitFor(() => {
      expect(received).toHaveLength(1);
    }, { timeout: 3000 });

    conn.close();
    // After close, no more events should arrive
    expect(received).toHaveLength(1);
  });
});

describe("checkSessionStatus", () => {
  it("returns completed when session has current_status=completed", async () => {
    server.use(
      http.get("/api/v1/sessions/:sessionId", () => {
        return HttpResponse.json({ current_status: "completed" });
      }),
    );

    const result = await checkSessionStatus("sess-done");
    expect(result).toEqual({ status: "completed" });
  });

  it("returns failed when session has current_status=failed", async () => {
    server.use(
      http.get("/api/v1/sessions/:sessionId", () => {
        return HttpResponse.json({ current_status: "failed" });
      }),
    );

    const result = await checkSessionStatus("sess-failed");
    expect(result).toEqual({ status: "failed" });
  });

  it("returns uncompleted when the round was filter-rejected", async () => {
    server.use(
      http.get("/api/v1/sessions/:sessionId", () => {
        return HttpResponse.json({ current_status: "uncompleted" });
      }),
    );

    const result = await checkSessionStatus("sess-rejected");
    expect(result).toEqual({ status: "uncompleted" });
  });

  it("returns in_progress when session is still running", async () => {
    server.use(
      http.get("/api/v1/sessions/:sessionId", () => {
        return HttpResponse.json({ current_status: "generating" });
      }),
    );

    const result = await checkSessionStatus("sess-running");
    expect(result).toEqual({ status: "in_progress" });
  });

  it("returns not_found when session does not exist (404)", async () => {
    server.use(
      http.get("/api/v1/sessions/:sessionId", () => {
        return HttpResponse.json(
          { detail: "Not found" },
          { status: 404 },
        );
      }),
    );

    const result = await checkSessionStatus("sess-unknown");
    expect(result).toEqual({ status: "not_found" });
  });
});
