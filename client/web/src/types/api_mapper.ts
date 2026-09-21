// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import type { TerraformProvider } from "@/types/api";

// ─── Mapping Service (mapping:8081) ────────────────────────

export interface ResolveRequest {
  identifier: string;
  // The wizard never sends this — resolution runs at the repository
  // step, before a provider has been picked. It exists for contract
  // completeness and for callers other than the wizard.
  terraform_provider?: TerraformProvider | null;
}

// `terraform_provider` and `scope_id` are the mapper's best effort, and
// null means "unknown, ask the user" rather than "there is none".
export interface ResolveResponse {
  repo_url: string;
  identifier: string;
  terraform_provider?: TerraformProvider | null;
  scope_id?: string | null;
}
