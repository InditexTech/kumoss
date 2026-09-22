// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * POST /notifications — the support request behind the "Contact team"
 * button, which is the action a user reaches for when apply is locked.
 *
 * Mirrors `core/src/api/v1/notifications.py`: **202** with a delivery id,
 * 502 when the notifications service accepted nothing, 503 when it is
 * disabled. The audience is derived server-side, so the request body is
 * taken as-is and never echoed back.
 */

import { http, HttpResponse, delay } from "msw";
import { matchQueryTrigger, QUERY_TRIGGER } from "../triggers";
import type {
  Notification,
  NotificationAccepted,
} from "@/types/api_notifications";

let nextDeliveryId = 1;

export const notificationHandlers = [
  http.post("/api/v1/notifications", async ({ request }) => {
    await delay(200);
    const body = (await request.json()) as Notification;

    // The trigger can ride in either free-text field the user controls.
    const trigger =
      matchQueryTrigger(body.subject ?? "") ?? matchQueryTrigger(body.body ?? "");
    if (trigger === QUERY_TRIGGER.NOTIFY_FAILED) {
      return HttpResponse.json(
        { detail: "Notification was not delivered." },
        { status: 502 },
      );
    }

    const response: NotificationAccepted = {
      delivery_id: `mock-delivery-${nextDeliveryId++}`,
    };
    return HttpResponse.json(response, { status: 202 });
  }),
];
