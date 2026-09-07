// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * WORKFLOW: Initial Information
 *
 * A workflow orchestrates multiple service calls in sequence.
 * It does NOT hold React state — it receives inputs, calls services,
 * and returns a result (or throws). The hook layer above handles state.
 *
 * Pattern to follow when creating a new workflow:
 *   1. Import only from services (never from hooks or components).
 *   2. Accept a plain params object — no React types.
 *   3. Return a typed result object so the hook knows what to store.
 *   4. Throw on unrecoverable errors; return { ok: false, ... } for
 *      expected business failures (user can retry).
 *   5. Accept an optional AbortSignal so the hook can cancel on unmount.
 *
 *
 * Initial information workflow actions:
 *
 * 1. Authorize the user with the provided information, this includes:
 *   - Checking if the project exist in the cloud
 *   - Checking if the user has access to the project/environment/cloud combination
 * 2. Upload the project
 *
 * Possible errors:
 * - Project not found in the cloud, ui message update and retry project input
 * - User not authorized, ui message update
 * - Upload failed, ui message update and retry project repo input
 */

import { authorizeUser } from "@/services/core/authorization";
import type { AuthorizeResponse } from "@/types/api";

// ─── Workflow input / output types ─────────────────────────────

export interface InitialInfoParams {
  repositoryUrl: string;
  query: string;
  cloud?: string;
  environment?: string;
}

/** Discriminated union — callers switch on `ok` to handle both paths. */
export type InitialInfoResult =
  | {
      ok: true;
      authorization: AuthorizeResponse;
    }
  | {
      ok: false;
      failedStep: "authorize";
      message: string;
    };

// ─── The workflow function ─────────────────────────────────────

export async function runInitialInfoWorkflow(
  params: InitialInfoParams,
  _signal?: AbortSignal,
): Promise<InitialInfoResult> {
  // Authorize: check if the user has permission on this
  // project/environment/cloud combination.
  const authResponse = await authorizeUser({
    cloud: params.cloud ?? "",
    project_name: params.repositoryUrl,
    environment: params.environment ?? "",
  });

  if (!authResponse.result) {
    return {
      ok: false,
      failedStep: "authorize",
      message: authResponse.message,
    };
  }

  return {
    ok: true,
    authorization: authResponse,
  };
}
