// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import type { ApiOptions } from "@/types";

const DEFAULT_TIMEOUT_MS = 60_000;

export class ApiError extends Error {
  status: number;
  body: unknown;
  detail: string | undefined;

  constructor(status: number, body: unknown) {
    const detail = extractDetail(body);
    super(detail ?? `API request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
    this.detail = detail;
  }
}

export class ApiTimeoutError extends ApiError {
  constructor(timeoutMs: number) {
    super(0, null);
    this.name = "ApiTimeoutError";
    this.message = `API request timed out after ${timeoutMs}ms`;
  }
}

function extractDetail(body: unknown): string | undefined {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return undefined;
}

export async function apiFetch<T = unknown>(
  path: string,
  options: ApiOptions = {},
): Promise<T> {
  const { headers, signal, timeout = DEFAULT_TIMEOUT_MS, ...rest } = options;

  const controller = new AbortController();
  if (signal)
    signal.addEventListener("abort", () => controller.abort(signal.reason));

  const timeoutId = setTimeout(() => controller.abort("timeout"), timeout);

  let response: Response;
  try {
    response = await fetch(path, {
      headers: {
        "Content-Type": "application/json",
        accept: "application/json",
        ...headers,
      },
      credentials: "include",
      signal: controller.signal,
      ...rest,
    });
  } catch (error: unknown) {
    clearTimeout(timeoutId);
    if (error instanceof DOMException && error.name === "AbortError") {
      if (signal?.aborted) throw error;
      throw new ApiTimeoutError(timeout);
    }
    throw error;
  }

  clearTimeout(timeoutId);

  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = await response.text().catch(() => null);
    }
    throw new ApiError(response.status, body);
  }

  if (response.status === 204) return undefined as T;

  const contentType = response.headers.get("content-type");
  const text = await response.text();
  if (!text) {
    throw new ApiError(0, {
      detail: "Expected a response body but received an empty response",
    });
  }

  if (contentType?.includes("application/json")) {
    return JSON.parse(text);
  }

  throw new ApiError(0, {
    detail: `Expected JSON response but received ${contentType ?? "unknown content-type"}`,
  });
}
