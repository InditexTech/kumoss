// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { http, HttpResponse } from "msw";
import { mockState } from "./state";

export const handlers = [
  http.get("/api/v1/sessions/:sessionId", ({ params }) => {
    const detail = mockState.getSession(params.sessionId as string);
    if (!detail) {
      return HttpResponse.json({ detail: "Session not found" }, { status: 404 });
    }
    return HttpResponse.json(detail);
  }),

  http.get("/api/v1/sessions", () => {
    const items = mockState.listSessions();
    return HttpResponse.json({
      items,
      total: items.length,
      page: 1,
      page_size: 10,
      total_pages: 1,
    });
  }),
];
