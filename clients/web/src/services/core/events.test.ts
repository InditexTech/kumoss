import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/mocks/server";
import { mockState } from "@/mocks/state";
import { subscribeToSession, getSessionData, unsubscribeSession } from "./events";

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

  it("calls onerror on non-OK response", async () => {
    server.use(
      http.get("/api/v1/events/subscribe/:sessionId", () => {
        return new HttpResponse(null, { status: 500 });
      }),
    );

    const onerror = vi.fn();
    const conn = subscribeToSession("bad-session");
    conn.onerror = onerror;

    await vi.waitFor(() => {
      expect(onerror).toHaveBeenCalled();
    }, { timeout: 3000 });

    conn.close();
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

describe("getSessionData", () => {
  it("returns payload for completed session", async () => {
    mockState.createSession("sess-1", {
      operationType: "generate",
      repoUri: "https://dev.azure.com/org/repo",
      cloud: "azure",
      environment: "dev",
      userId: "user@test.com",
      query: "deploy a VM",
      iacPath: null,
    });
    mockState.updateStatus("sess-1", "completed");

    const payload = await getSessionData("sess-1");

    expect(payload.id).toBe("sess-1");
    expect(payload.cloud).toBe("azure");
    expect(payload.environment).toBe("dev");
  });

  it("throws on unknown session (404)", async () => {
    await expect(getSessionData("nonexistent")).rejects.toThrow();
  });

  it("throws when session is in progress (409)", async () => {
    mockState.createSession("sess-2", {
      operationType: "generate",
      repoUri: "https://dev.azure.com/org/repo",
      cloud: "azure",
      environment: "dev",
      userId: "user@test.com",
      query: "deploy a VM",
      iacPath: null,
    });
    // Status is "pending" by default (not "completed")

    await expect(getSessionData("sess-2")).rejects.toThrow();
  });
});

describe("unsubscribeSession", () => {
  it("resolves successfully (204)", async () => {
    await expect(unsubscribeSession("any-session")).resolves.toBeUndefined();
  });
});
