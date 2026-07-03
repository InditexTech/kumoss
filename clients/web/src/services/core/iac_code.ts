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

export interface ScanRepositoryResponse {
  repo_url: string
  terraform_paths: string[];
}

/** POST /v1/repository/scan — Scan a repo for IaC paths */
export async function scanRepository(
  repo_url: string,
): Promise<ScanRepositoryResponse> {
  return apiFetch<ScanRepositoryResponse>(`${REPO_BASE}/scan`, {
    method: "POST",
    body: JSON.stringify({ repo_url }),
  });
}
