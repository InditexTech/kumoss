// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { apiFetch } from "@/services/api";
import type {
  CreatePrRequest,
  MergePrRequest,
  PullRequestDTO,
} from "@/types/api";

const REPO_BASE = "/api/v1/repository";

// PR creation runs synchronous LLM work server-side; well above the 60s default.
const CREATE_PR_TIMEOUT_MS = 300_000;

/** PUT /v1/repository/pr — Create a Pull Request from the session's branch */
export async function createPullRequest(
  request: CreatePrRequest,
): Promise<PullRequestDTO> {
  return apiFetch<PullRequestDTO>(`${REPO_BASE}/pr`, {
    method: "PUT",
    body: JSON.stringify(request),
    timeout: CREATE_PR_TIMEOUT_MS,
  });
}

/** PUT /v1/repository/pr/merge — Merge the session's latest PR (204) */
export async function mergePullRequest(
  request: MergePrRequest,
): Promise<void> {
  return apiFetch<void>(`${REPO_BASE}/pr/merge`, {
    method: "PUT",
    body: JSON.stringify(request),
  });
}

export interface ParseRepositoryResponse {
  roots: string[];
}

/** POST /v1/repository/parse — Parse a repo for IaC root-module directories */
export async function parseRepository(
  repo_uri: string,
): Promise<ParseRepositoryResponse> {
  return apiFetch<ParseRepositoryResponse>(`${REPO_BASE}/parse`, {
    method: "POST",
    body: JSON.stringify({ repo_uri }),
  });
}
