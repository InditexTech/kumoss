// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import type { ApiOptions } from "@/types";
import { getAccessToken, UNAUTHORIZED_EVENT } from "@/services/token";

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
    if (typeof detail === "string") return humanizeDetail(detail);
  }
  return undefined;
}

/**
 * The backend relays upstream failures (e.g. GitHub's
 * `{"message": "Validation Failed", "errors": [...]}`) as a JSON-encoded
 * string inside `detail`. Unwrap it into a readable sentence; anything
 * that isn't such a payload passes through untouched.
 */
function humanizeDetail(detail: string): string {
  const trimmed = detail.trim();
  if (!trimmed.startsWith("{")) return detail;
  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (!parsed || typeof parsed !== "object") return detail;
    const { message, errors } = parsed as {
      message?: unknown;
      errors?: unknown;
    };
    const parts: string[] = [];
    if (typeof message === "string" && message) parts.push(message);
    if (Array.isArray(errors)) {
      for (const err of errors) {
        if (err && typeof err === "object") {
          const msg = (err as { message?: unknown }).message;
          if (typeof msg === "string" && msg) parts.push(msg);
        } else if (typeof err === "string" && err) {
          parts.push(err);
        }
      }
    }
    if (parts.length === 0) return detail;
    return parts.length > 1
      ? `${parts[0]}: ${parts.slice(1).join("; ")}`
      : parts[0];
  } catch {
    return detail;
  }
}

/** Best human-readable message for an error thrown by `apiFetch`. */
export function getApiErrorMessage(
  err: unknown,
  fallback = "An unexpected error occurred",
): string {
  if (err instanceof ApiError) return err.detail ?? err.message;
  if (err instanceof Error && err.message) return err.message;
  return fallback;
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

  const token = getAccessToken();

  let response: Response;
  try {
    response = await fetch(path, {
      headers: {
        "Content-Type": "application/json",
        accept: "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
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
    if (response.status === 401) {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
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
