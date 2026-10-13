// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { beforeEach, afterEach } from "vitest";
import { server } from "./server";
import { authConfigHandler, DEFAULT_AUTH_CONFIG } from "./handlers";
import { loadAuthConfig } from "@/services/auth";

/**
 * Run the enclosing `describe` against a different object store's
 * metadata header prefix, e.g. Azure's `x-ms-meta-`. Call at describe
 * level, not inside a test.
 *
 * The config lives in a module-level singleton in `services/auth`, so it
 * is re-served and re-loaded rather than poked directly — no test-only
 * setter exists there, and adding one would be a production backdoor.
 *
 * Both hooks install a handler explicitly instead of leaning on
 * `resetHandlers()`: the global afterEach that resets handlers and this
 * one are not ordered against each other, so the restore reloads from a
 * handler it put there itself.
 */
export function useMetadataHeaderPrefix(prefix: string): void {
  beforeEach(async () => {
    server.use(
      authConfigHandler({
        ...DEFAULT_AUTH_CONFIG,
        artifact_metadata_header_prefix: prefix,
      }),
    );
    await loadAuthConfig();
  });

  afterEach(async () => {
    server.use(authConfigHandler(DEFAULT_AUTH_CONFIG));
    await loadAuthConfig();
  });
}
