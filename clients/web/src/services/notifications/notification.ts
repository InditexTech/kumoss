// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { apiFetch } from "@/services/api";
import { Notification, NotificationAccepted } from "@/types/api_notifications";

const BASE_URL = "/api/v1/";

/** Send a notification to the backend for processing and delivery */
export async function sendNotification(
  notification: Notification,
): Promise<NotificationAccepted> {
  return apiFetch<NotificationAccepted>(`${BASE_URL}notifications`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(notification),
  });
}
