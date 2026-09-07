// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * WORKFLOW: Terraform Action
 *
 * Triggers the appropriate IaC endpoint based on the current mode,
 * returning a session ID that the hook layer uses for SSE subscription.
 *
 * Actions:
 * 1. Select the IaC endpoint based on mode (generate / drift / apply)
 * 2. Call the endpoint with the user's query and session context
 * 3. Return the session ID for SSE tracking
 */

import {
  generateInfrastructure,
  driftDetectionRemediation,
  applyInfrastructure,
} from "@/services/core/iac_actions";
import type { IacSessionResponse, TerraformProvider } from "@/types/api";
import type { Mode } from "@/types/ui";
import { MODE } from "@/types/ui";

// ─── Workflow input / output types ─────────────────────────────

export interface TerraformActionParams {
  query: string;
  mode: Mode;
  repoUri?: string;
  terraformProviders?: TerraformProvider;
  scopeId?: string;
  iacPath?: string;
  sessionId?: string;
}

export interface TerraformActionResult {
  sessionId: string;
}

// ─── The workflow function ─────────────────────────────────────

export async function runTerraformActionWorkflow(
  params: TerraformActionParams,
  _signal?: AbortSignal,
): Promise<TerraformActionResult> {
  let response: IacSessionResponse;

  if (params.mode === MODE.IMPORT) {
    // Apply reuses the session's stored plan; it takes no query or targets.
    response = await applyInfrastructure({
      session_id: params.sessionId ?? "",
    });
    return { sessionId: response.session_id };
  }

  const baseRequest = params.sessionId
    ? {
        session_id: params.sessionId,
        q: params.query,
      }
    : {
        repo_uri: params.repoUri,
        q: params.query,
        terraform_providers: params.terraformProviders,
        scope_id: params.scopeId,
        iac_path: params.iacPath ?? null,
      };

  switch (params.mode) {
    case MODE.GENERATE:
      response = await generateInfrastructure(baseRequest);
      break;
    case MODE.DRIFT:
      response = await driftDetectionRemediation({
        ...baseRequest,
        is_partial: false,
      });
      break;
    case MODE.PARTIAL_DRIFT:
      response = await driftDetectionRemediation({
        ...baseRequest,
        is_partial: true,
      });
      break;
  }

  return { sessionId: response.session_id };
}
