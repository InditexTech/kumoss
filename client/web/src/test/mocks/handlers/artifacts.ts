// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * Blob storage stand-in. Real artifact URLs are presigned and answered
 * by the storage account, not the API — no cookies, no bearer token —
 * so these live outside `/api/v1` on purpose.
 */

import { http, HttpResponse, delay } from "msw";
import { ARTIFACT_BASE, resolveArtifact } from "../data";

export const artifactHandlers = [
  http.get(`${ARTIFACT_BASE}/*`, async ({ request }) => {
    await delay(120);
    const key = decodeURIComponent(
      new URL(request.url).pathname.slice(ARTIFACT_BASE.length + 1),
    );
    const artifact = resolveArtifact(key);
    if (!artifact) {
      // What an expired SAS token looks like; the client answers with a
      // session re-read and one retry.
      return HttpResponse.text("AuthenticationFailed", { status: 403 });
    }
    return HttpResponse.text(artifact.content, {
      headers: { "Content-Type": artifact.contentType },
    });
  }),
];
