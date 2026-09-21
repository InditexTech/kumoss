// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * GET /events/subscribe/{id} — the progress stream.
 *
 * Faithful to `core/src/api/v1/events.py`: a `: keepalive` comment
 * first, then `data: {...}` frames carrying `{status_msg, detail}`, and
 * the server closes the stream itself once the session reaches
 * COMPLETED, UNCOMPLETED or FAILED. Artifacts land during the REPORT
 * stage, before the terminal frame — so a client that re-reads the
 * session on COMPLETED always finds them.
 */

import { http, HttpResponse, delay } from "msw";
import { SSE_KEEPALIVE, sseOptions } from "../data";
import {
  applyStep,
  materializeArtifacts,
  runSequence,
  takePending,
} from "../runtime";
import { lastSessionStatus, mockState } from "../state";
import type { SessionEventData } from "@/types/api";

const encoder = new TextEncoder();

function frame(data: SessionEventData): Uint8Array {
  return encoder.encode(`data: ${JSON.stringify(data)}\n\n`);
}

const SSE_HEADERS = {
  "Content-Type": "text/event-stream",
  "Cache-Control": "no-cache",
  Connection: "keep-alive",
  "X-Accel-Buffering": "no",
};

export const eventHandlers = [
  http.get("/api/v1/events/subscribe/:sessionId", async ({ params }) => {
    const sessionId = params.sessionId as string;
    if (!mockState.getSession(sessionId)) {
      return HttpResponse.json({ detail: "Session not found" }, { status: 404 });
    }

    // The backend sleeps before streaming; the client's stale-terminal
    // guard relies on that window existing.
    await delay(Math.round(500 / sseOptions.speed));
    const run = takePending(sessionId);

    const stream = new ReadableStream<Uint8Array>({
      async start(controller) {
        controller.enqueue(encoder.encode(SSE_KEEPALIVE));

        // No run in flight: the poll finds the session's resting status,
        // emits it once and the stream closes.
        if (!run) {
          const detail = mockState.getSession(sessionId);
          const last = detail ? lastSessionStatus(detail) : undefined;
          if (last) {
            controller.enqueue(
              frame({
                status_msg: last.status.toUpperCase() as SessionEventData["status_msg"],
                detail: { message: last.message ?? "" },
              }),
            );
          }
          controller.close();
          return;
        }

        let materialized = false;
        for (const step of runSequence(run)) {
          await delay(step.delay);
          if (step.data.status_msg === "REPORT" && !materialized) {
            materializeArtifacts(run);
            materialized = true;
          }
          applyStep(run, step);
          controller.enqueue(frame(step.data));
        }
        controller.close();
      },
    });

    return new HttpResponse(stream, { headers: SSE_HEADERS });
  }),
];
