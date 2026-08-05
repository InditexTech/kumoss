// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { apiFetch, ApiError } from "@/services/api";
import { SessionPayloadResponse, normalizeHistory } from "@/types/api";

const BASE = "/api/v1/events";
const SSE_MAX_RETRIES = 3;
const SSE_RETRY_BASE_MS = 2_000;

/** Minimal interface matching the subset of EventSource used by consumers. */
export interface SseConnection {
  onmessage: ((event: { data: string }) => void) | null;
  onerror: (() => void) | null;
  close(): void;
}

/** Subscribe to session SSE events using fetch + ReadableStream.
 *  Returns an SseConnection with the same onmessage/onerror/close
 *  interface that EventSource provides, but supports custom headers.
 *  Retries transparently on connection failures (up to SSE_MAX_RETRIES). */
export function subscribeToSession(
  sessionId: string,
  headers?: Record<string, string>,
  opts?: { retryBaseMs?: number },
): SseConnection {
  const retryBaseMs = opts?.retryBaseMs ?? SSE_RETRY_BASE_MS;
  const controller = new AbortController();

  const connection: SseConnection = {
    onmessage: null,
    onerror: null,
    close() {
      controller.abort();
    },
  };

  (async () => {
    for (let attempt = 0; attempt <= SSE_MAX_RETRIES; attempt++) {
      if (controller.signal.aborted) return;

      if (attempt > 0) {
        const delay = retryBaseMs * 2 ** (attempt - 1);
        await new Promise<void>((resolve) => {
          const timer = setTimeout(resolve, delay);
          controller.signal.addEventListener(
            "abort",
            () => {
              clearTimeout(timer);
              resolve();
            },
            { once: true },
          );
        });
        if (controller.signal.aborted) return;
      }

      try {
        const response = await fetch(
          `${BASE}/subscribe/${encodeURIComponent(sessionId)}`,
          {
            headers: { accept: "text/event-stream", ...headers },
            credentials: "include",
            signal: controller.signal,
          },
        );

        if (!response.ok || !response.body) {
          if (attempt < SSE_MAX_RETRIES) continue;
          connection.onerror?.();
          return;
        }

        const reader = response.body
          .pipeThrough(new TextDecoderStream())
          .getReader();

        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += value;
          const blocks = buffer.split("\n\n");
          buffer = blocks.pop()!;

          for (const block of blocks) {
            const data = block
              .split("\n")
              .filter((line) => line.startsWith("data:"))
              .map((line) => line.slice(5).trimStart())
              .join("\n");

            if (data) {
              connection.onmessage?.({ data });
            }
          }
        }

        if (controller.signal.aborted) return;
        throw new Error("SSE stream closed");
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        if (attempt < SSE_MAX_RETRIES) continue;
        connection.onerror?.();
      }
    }
  })();

  return connection;
}

/** GET /v1/events/get/{session_id} — Get the corresponding session related data once the session has finished */
export async function getSessionData(
  sessionId: string,
): Promise<SessionPayloadResponse> {
  const raw = await apiFetch<SessionPayloadResponse>(
    `${BASE}/get/${encodeURIComponent(sessionId)}`,
  );
  // TEMPORAL FIX: normalize {user, assistant} turn pairs from backend into {role, content} entries
  raw.full_history = normalizeHistory(raw.full_history);

  // // TODO: remove — workaround for backend not including `response` in full_history
  // if (raw.response) {
  //   const lastEntry = raw.full_history[raw.full_history.length - 1];
  //   if (!lastEntry || lastEntry.content !== raw.response) {
  //     raw.full_history.push({ role: "assistant", content: raw.response });
  //   }
  // }

  return raw;
}

export type SessionCheckResult =
  | { status: "completed" }
  | { status: "failed" }
  | { status: "in_progress" }
  | { status: "not_found" };

/** Check whether a session has finished without subscribing to SSE. */
export async function checkSessionStatus(
  sessionId: string,
): Promise<SessionCheckResult> {
  try {
    const data = await apiFetch<{ current_status: string }>(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}`,
    );
    if (data.current_status === "completed") return { status: "completed" };
    if (data.current_status === "failed") return { status: "failed" };
    return { status: "in_progress" };
  } catch (err) {
    if (err instanceof ApiError && err.status === 404)
      return { status: "not_found" };
    throw err;
  }
}

/** DELETE /v1/events/unsubscribe/{session_id} — Delete session data */
export async function unsubscribeSession(sessionId: string): Promise<void> {
  return apiFetch<void>(
    `${BASE}/unsubscribe/${encodeURIComponent(sessionId)}`,
    { method: "DELETE" },
  );
}
