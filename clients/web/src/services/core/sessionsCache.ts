// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import type { UserSessionInfo } from "@/types/api";

interface CachedSessions {
  sessions: UserSessionInfo[];
  total: number;
  fetchedAt: number;
}

const CACHE_TTL = 30_000;

let cache: CachedSessions | null = null;

export function getCachedSessions(): CachedSessions | null {
  if (cache && Date.now() - cache.fetchedAt < CACHE_TTL) return cache;
  return null;
}

export function setCachedSessions(sessions: UserSessionInfo[], total: number) {
  cache = { sessions, total, fetchedAt: Date.now() };
}

export function invalidateSessionsCache() {
  cache = null;
}
