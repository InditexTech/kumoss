import { apiFetch } from "@/services/api";
import { SessionPayloadResponse } from "@/types/api";

const BASE = "/api/v1/events";

/** Minimal interface matching the subset of EventSource used by consumers. */
export interface SseConnection {
  onmessage: ((event: { data: string }) => void) | null;
  onerror: (() => void) | null;
  close(): void;
}

/** Subscribe to session SSE events using fetch + ReadableStream.
 *  Returns an SseConnection with the same onmessage/onerror/close
 *  interface that EventSource provides, but supports custom headers. */
export function subscribeToSession(
  sessionId: string,
  headers?: Record<string, string>,
): SseConnection {
  const controller = new AbortController();

  const connection: SseConnection = {
    onmessage: null,
    onerror: null,
    close() {
      controller.abort();
    },
  };

  (async () => {
    try {
      const response = await fetch(
        `${BASE}/subscribe/${encodeURIComponent(sessionId)}`,
        {
          headers: {
            accept: "text/event-stream",
            ...headers,
          },
          credentials: "include",
          signal: controller.signal,
        },
      );

      if (!response.ok || !response.body) {
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
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      connection.onerror?.();
    }
  })();

  return connection;
}

/** GET /v1/events/get/{session_id} — Get the corresponding session related data once the session has finished */
export async function getSessionData(
  sessionId: string,
): Promise<SessionPayloadResponse> {
  return apiFetch<SessionPayloadResponse>(
    `${BASE}/get/${encodeURIComponent(sessionId)}`,
  );
}

/** DELETE /v1/events/unsubscribe/{session_id} — Delete session data */
export async function unsubscribeSession(sessionId: string): Promise<void> {
  return apiFetch<void>(
    `${BASE}/unsubscribe/${encodeURIComponent(sessionId)}`,
    { method: "DELETE" },
  );
}
