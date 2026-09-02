// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

// ─── Mapping Service (mapping:8081) ────────────────────────

export interface ResolveRequest {
  identifier: string;
  cloud?: string | null;
  environment?: string | null;
}

export interface ResolveResponse {
  repo_url: string;
  project?: string | null;
  branch?: string | null;
  path?: string | null;
}
