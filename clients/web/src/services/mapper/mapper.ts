import type { ResolveRequest, ResolveResponse } from "@/types/api_mapper";
import { apiFetch } from "@/services/api";

const BASE = "/api/v1/mapping";

export async function resolveProject(
  request: ResolveRequest,
): Promise<ResolveResponse> {
  return apiFetch<ResolveResponse>(`${BASE}/resolve`, {
    method: "POST",
    body: JSON.stringify(request),
  });
}
