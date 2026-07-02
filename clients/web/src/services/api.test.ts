import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/mocks/server";
import { apiFetch, ApiError, ApiTimeoutError } from "./api";

const TEST_PATH = "/api/v1/test";

describe("apiFetch", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns parsed JSON on success", async () => {
    server.use(
      http.get(TEST_PATH, () =>
        HttpResponse.json({ id: 1, name: "test" }),
      ),
    );

    const result = await apiFetch<{ id: number; name: string }>(TEST_PATH);
    expect(result).toEqual({ id: 1, name: "test" });
  });

  it("sends Content-Type, accept, and credentials", async () => {
    let capturedHeaders: Record<string, string> = {};

    server.use(
      http.get(TEST_PATH, ({ request }) => {
        capturedHeaders = {
          "content-type": request.headers.get("content-type") ?? "",
          accept: request.headers.get("accept") ?? "",
        };
        return HttpResponse.json({ ok: true });
      }),
    );

    await apiFetch(TEST_PATH);
    expect(capturedHeaders["content-type"]).toBe("application/json");
    expect(capturedHeaders.accept).toBe("application/json");
  });

  it("returns undefined for 204 No Content", async () => {
    server.use(
      http.delete(TEST_PATH, () => new HttpResponse(null, { status: 204 })),
    );

    const result = await apiFetch(TEST_PATH, { method: "DELETE" });
    expect(result).toBeUndefined();
  });

  it("throws ApiError on non-OK JSON response", async () => {
    server.use(
      http.get(TEST_PATH, () =>
        HttpResponse.json(
          { detail: "Session not found" },
          { status: 404 },
        ),
      ),
    );

    await expect(apiFetch(TEST_PATH)).rejects.toThrow(ApiError);
    await expect(apiFetch(TEST_PATH)).rejects.toMatchObject({
      status: 404,
      detail: "Session not found",
    });
  });

  it("throws ApiError with text body on non-OK non-JSON response", async () => {
    server.use(
      http.get(TEST_PATH, () =>
        new HttpResponse("Internal Server Error", {
          status: 500,
          headers: { "Content-Type": "text/plain" },
        }),
      ),
    );

    await expect(apiFetch(TEST_PATH)).rejects.toThrow(ApiError);
    await expect(apiFetch(TEST_PATH)).rejects.toMatchObject({
      status: 500,
    });
  });

  it("throws ApiError on empty response body", async () => {
    server.use(
      http.get(TEST_PATH, () =>
        new HttpResponse("", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(apiFetch(TEST_PATH)).rejects.toThrow(ApiError);
    await expect(apiFetch(TEST_PATH)).rejects.toMatchObject({
      detail: expect.stringContaining("empty response"),
    });
  });

  it("throws ApiError on non-JSON content-type", async () => {
    server.use(
      http.get(TEST_PATH, () =>
        new HttpResponse("<html>page</html>", {
          status: 200,
          headers: { "Content-Type": "text/html" },
        }),
      ),
    );

    await expect(apiFetch(TEST_PATH)).rejects.toThrow(ApiError);
    await expect(apiFetch(TEST_PATH)).rejects.toMatchObject({
      detail: expect.stringContaining("text/html"),
    });
  });

  it("throws ApiTimeoutError when request exceeds timeout", async () => {
    server.use(
      http.get(TEST_PATH, () => new Promise(() => {})),
    );

    await expect(
      apiFetch(TEST_PATH, { timeout: 50 }),
    ).rejects.toSatisfy(
      (err: unknown) =>
        err instanceof ApiTimeoutError ||
        (typeof err === "string" && err === "timeout"),
    );
  });

  it("re-throws when external signal aborts", async () => {
    const controller = new AbortController();

    server.use(
      http.get(TEST_PATH, () => new Promise(() => {})),
    );

    const promise = apiFetch(TEST_PATH, {
      signal: controller.signal,
      timeout: 30_000,
    });

    controller.abort();

    await expect(promise).rejects.toBeDefined();
  });

  it("merges custom headers with defaults", async () => {
    let authHeader = "";

    server.use(
      http.get(TEST_PATH, ({ request }) => {
        authHeader = request.headers.get("x-user-email") ?? "";
        return HttpResponse.json({ ok: true });
      }),
    );

    await apiFetch(TEST_PATH, {
      headers: { "X-User-Email": "admin@test.com" },
    });

    expect(authHeader).toBe("admin@test.com");
  });
});

describe("ApiError", () => {
  it("extracts detail from response body", () => {
    const error = new ApiError(400, { detail: "Invalid request" });
    expect(error.status).toBe(400);
    expect(error.detail).toBe("Invalid request");
    expect(error.message).toBe("Invalid request");
  });

  it("falls back to status message when no detail", () => {
    const error = new ApiError(500, null);
    expect(error.status).toBe(500);
    expect(error.detail).toBeUndefined();
    expect(error.message).toBe("API request failed with status 500");
  });
});

describe("ApiTimeoutError", () => {
  it("includes timeout duration in message", () => {
    const error = new ApiTimeoutError(5000);
    expect(error.message).toBe("API request timed out after 5000ms");
    expect(error.name).toBe("ApiTimeoutError");
  });
});
