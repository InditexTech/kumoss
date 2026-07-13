// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import type { UserSessionInfo, AdminSessionInfo } from "@/types/api";

export type SessionItem = UserSessionInfo | AdminSessionInfo;

export function isAdminSession(s: SessionItem): s is AdminSessionInfo {
  return "repository_id" in s;
}

export interface SessionRow {
  session_id: string;
  user_id: string;
  repo_uri: string;
  cloud_provider: string;
  environment: string;
  status: string;
  in_flight: boolean;
  created_at: string;
  operation_type: string | null;
  initial_query: string | null;
  apply_allowed: boolean;
}

export function fromUserSession(s: UserSessionInfo): SessionRow {
  return {
    session_id: s.session_id,
    user_id: s.user_id,
    repo_uri: s.repo_uri,
    cloud_provider: s.cloud_provider,
    environment: s.environment,
    status: s.status,
    in_flight: s.in_flight,
    created_at: s.created_at,
    operation_type: s.operation_type ?? null,
    initial_query: s.initial_query ?? null,
    apply_allowed: s.apply_allowed,
  };
}

export function extractProjectName(repoUri: string): string {
  const segments = repoUri.replace(/\/+$/, "").split("/");
  return segments[segments.length - 1] || repoUri;
}
