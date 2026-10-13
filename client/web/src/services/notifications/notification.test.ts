// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { ApiError } from "@/services/api";
import { NotificationSeverity } from "@/types/api_notifications";
import { sendNotification } from "./notification";

const NOTIFICATION = {
  kind: "support.user_question",
  severity: NotificationSeverity.INFO,
  subject: "Support request from someone@example.com",
  body: "How do I import a resource group?",
  audience: ["someone@example.com"],
  context: { cloud: "azure" },
};

describe("sendNotification", () => {
  it("posts the notification to /api/v1/notifications and returns the delivery id", async () => {
    let received: unknown = null;
    server.use(
      http.post("/api/v1/notifications", async ({ request }) => {
        received = await request.json();
        return HttpResponse.json(
          { delivery_id: "8b5df7d0-c3dd-4db4-a93e-fdd5973be524" },
          { status: 202 },
        );
      }),
    );

    const result = await sendNotification(NOTIFICATION);

    expect(result.delivery_id).toBe("8b5df7d0-c3dd-4db4-a93e-fdd5973be524");
    expect(received).toEqual(NOTIFICATION);
  });

  it("throws an ApiError carrying the backend detail when delivery is not configured", async () => {
    server.use(
      http.post("/api/v1/notifications", () =>
        HttpResponse.json(
          { detail: "notifications service is disabled or has no endpoint configured" },
          { status: 503 },
        ),
      ),
    );

    const error = await sendNotification(NOTIFICATION).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(503);
    expect((error as ApiError).detail).toMatch(/disabled or has no endpoint/);
  });
});
