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
import type { IacSessionResponse } from "@/types/api";
import type { Mode } from "@/types/ui";
import { MODE } from "@/types/ui";

// ─── Workflow input / output types ─────────────────────────────

export interface TerraformActionParams {
  repoUri: string;
  query: string;
  cloud: string;
  environment: string;
  userId: string;
  mode: Mode;
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
  const baseRequest = params.sessionId
    ? {
        session_id: params.sessionId,
        q: params.query,
        user_id: params.userId,
      }
    : {
        repo_uri: params.repoUri,
        q: params.query,
        //cloud: params.cloud as "azure" | "gcp",
        cloud: "azure", //TODO: How can we retrieve this value from input params?
        environment: "dev", //TODO: hardcoded — derive from params.environment or iac_path
        user_id: params.userId,
        iac_path: params.iacPath ?? null,
      };

  let response: IacSessionResponse;

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
    case MODE.IMPORT:
      response = await applyInfrastructure(baseRequest);
      break;
  }

  return { sessionId: response.session_id };
}
