import { apiFetch } from "@/services/api";
import type {
  CreatePrRequest,
  RepositoryPrStatusResponse,
  ApprovePrRequest,
} from "@/types/api";

const REPO_BASE = "/api/v1/repository";

/** PUT /v1/repository/pr — Create a Pull Request from a session's branch */
export async function createPullRequest(
  request: CreatePrRequest,
): Promise<RepositoryPrStatusResponse> {
  return apiFetch<RepositoryPrStatusResponse>(`${REPO_BASE}/pr`, {
    method: "PUT",
    body: JSON.stringify(request),
  });
}

/** PATCH /v1/repository/approve_pr — Merge the PR with ID "id" into the default branch */
export async function approvePullRequest(
  request: ApprovePrRequest,
): Promise<RepositoryPrStatusResponse> {
  return apiFetch<RepositoryPrStatusResponse>(`${REPO_BASE}/approve_pr`, {
    method: "PATCH",
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
