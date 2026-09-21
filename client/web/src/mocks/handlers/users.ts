// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { http, HttpResponse } from "msw";
import { MOCK_ME } from "../data";
import type { UserMeResponse } from "@/types/api";

/** `/users/me` returns the caller's identity only — no issuer/subject. */
function toMe(): UserMeResponse {
  return {
    id: MOCK_ME.id,
    email: MOCK_ME.email,
    display_name: MOCK_ME.display_name,
    operation_role: MOCK_ME.operation_role,
    panel_role: MOCK_ME.panel_role,
  };
}

export const userHandlers = [
  http.get("/api/v1/users/me", () => HttpResponse.json(toMe())),
];
