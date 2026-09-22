// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { http, HttpResponse, delay } from "msw";
import { createMockAuthorizeResponse } from "../data";
import { matchCloudTrigger } from "../triggers";
import type { AuthConfigResponse, AuthorizeRequest } from "@/types/api";

/**
 * A blank `issuer_url` disables OIDC in the client (`main.tsx` awaits
 * this before rendering), which is what a local mock run wants.
 */
const AUTH_CONFIG: AuthConfigResponse = {
  issuer_url: "",
  client_id: "",
  audience: "",
  scope: "openid profile email",
};

export const authHandlers = [
  http.get("/api/v1/auth/config", () => HttpResponse.json(AUTH_CONFIG)),

  http.post("/api/v1/auth/authorize", async ({ request }) => {
    await delay(200);
    const body = (await request.json()) as AuthorizeRequest;
    const denied = matchCloudTrigger(body.cloud) !== null;
    return HttpResponse.json(
      createMockAuthorizeResponse(
        !denied,
        `${body.project_name} (${body.environment})`,
      ),
    );
  }),
];
