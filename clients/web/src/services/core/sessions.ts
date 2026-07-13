import { ApiError, apiFetch } from "@/services/api";
import type {
  AdminOperationItem,
  UserSessionInfo,
  UserSessionsListResponse,
} from "@/types/api";

const BASE = "/api/v1/sessions";

/** GET /api/v1/admin/sessions — List user sessions with pagination */
export async function listUserSessions(
  userEmail: string,
  params: {
    page?: number;
    page_size?: number;
    search?: string;
    status?: string;
    operation_type?: string;
  } = {},
): Promise<UserSessionsListResponse> {
  const query = new URLSearchParams();
  query.set("search", userEmail.split("@")[0]);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      query.set(key, String(value));
    }
  }
  return apiFetch<UserSessionsListResponse>(`${BASE}?${query.toString()}`);
}

/** GET /api/v1/sessions/{sessionId}/apply_allowed */
export async function checkApplyAllowed(sessionId: string): Promise<boolean> {
  const response = await apiFetch<{ apply_allowed: boolean }>(
    `${BASE}/${encodeURIComponent(sessionId)}/apply_allowed`,
  );
  return response.apply_allowed;
}

/** GET /api/v1/sessions/{sessionId} */
export async function getSession(
  sessionId: string,
): Promise<UserSessionInfo> {
  return apiFetch<UserSessionInfo>(
    `${BASE}/${encodeURIComponent(sessionId)}`,
  );
}

/** GET /api/v1/sessions/{sessionId}/operations */
export async function getSessionOperations(
  sessionId: string,
): Promise<AdminOperationItem[]> {
  try {
    return await apiFetch<AdminOperationItem[]>(
      `${BASE}/${encodeURIComponent(sessionId)}/operations`,
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return [];
    throw error;
  }
}

/** Fetch artifact content directly from its blob storage URL */
export async function fetchArtifactContent(blobUrl: string): Promise<string> {
  const response = await fetch(blobUrl);
  if (!response.ok) {
    throw new Error(`Failed to fetch artifact: ${response.status}`);
  }
  return response.text();
}
