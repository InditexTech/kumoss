// ─── Mapping Service (mapping:8081) ────────────────────────

export interface ResolveRequest {
  identifier: string;
  cloud?: string | null;
  environment?: string | null;
}

export interface ResolveResponse {
  identifier: string;
  project?: string | null;
  branch?: string | null;
  path?: string | null;
}
