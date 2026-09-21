// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { setupWorker } from "msw/browser";
// See the note in `server.ts`: "./handlers" resolves to the superseded
// `handlers.ts`, not this directory's `index.ts`.
import { handlers } from "./handlers/index";
import { seedMockData, seedReproData } from "./seed";

export const worker = setupWorker(...handlers);

/** Boot the Service Worker before the app issues its first request.
 *  `main.tsx` awaits this ahead of `loadAuthConfig()`, otherwise the
 *  bootstrap fetch escapes the interceptor and the app renders the
 *  bootstrap error screen. */
export async function startMockWorker(): Promise<void> {
  seedMockData();
  seedReproData();
  await worker.start({
    // Only /api/v1 is mocked. Assets, fonts and HMR pass through
    // silently; an unmocked API call is a gap worth shouting about,
    // because with no backend behind Vite it just fails to connect.
    onUnhandledRequest(request, print) {
      if (new URL(request.url).pathname.startsWith("/api/")) print.warning();
    },
    serviceWorker: { url: "/mockServiceWorker.js" },
  });
}
