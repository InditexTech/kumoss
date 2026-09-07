// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/** Fired on window whenever an API call is rejected with 401. */
export const UNAUTHORIZED_EVENT = "nebula:unauthorized";

type AccessTokenProvider = () => string | null | undefined;

let provider: AccessTokenProvider | null = null;

/** Registered once by the auth layer; null when auth is disabled. */
export function setAccessTokenProvider(fn: AccessTokenProvider | null): void {
  provider = fn;
}

/** Current bearer token, or null when auth is disabled / signed out. */
export function getAccessToken(): string | null {
  return provider?.() ?? null;
}
