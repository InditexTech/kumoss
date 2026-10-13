// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { WebStorageStateStore } from "oidc-client-ts";
import type { AuthProviderProps } from "react-oidc-context";
import { apiFetch } from "@/services/api";
import type { UserInfo } from "@/types";
import type { AuthConfigResponse, UserMeResponse } from "@/types/api";

let authConfig: AuthConfigResponse | null = null;

/** GET /api/v1/auth/config — fetched once by the bootstrap in main.tsx
 *  before the app renders; everything below reads the stored result. */
export async function loadAuthConfig(): Promise<void> {
  authConfig = await apiFetch<AuthConfigResponse>("/api/v1/auth/config");
}

/** Blank issuer = auth disabled (dev default; mirrors the core's config). */
export function isOidcEnabled(): boolean {
  return (authConfig?.issuer_url.trim() ?? "") !== "";
}

export function metadataHeaderPrefix(): string {
  return authConfig?.artifact_metadata_header_prefix || "x-amz-meta-";
}

/** State carried through the IdP round trip via `signinRedirect({ state })`. */
export interface SigninState {
  returnTo?: string;
}

export function buildOidcConfig(): AuthProviderProps {
  if (!authConfig) throw new Error("Auth config not loaded");
  const audience = authConfig.audience.trim();
  return {
    authority: authConfig.issuer_url.trim(),
    client_id: authConfig.client_id.trim(),
    redirect_uri: `${window.location.origin}/auth/callback`,
    post_logout_redirect_uri: window.location.origin,
    scope: authConfig.scope,
    automaticSilentRenew: true,
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
    // Auth0-style IdPs only issue a JWT access token when an audience is
    // requested explicitly; harmless elsewhere.
    ...(audience ? { extraQueryParams: { audience } } : {}),
    onSigninCallback: () => {
      window.history.replaceState({}, document.title, window.location.pathname);
    },
  };
}

export function toUserInfo(me: UserMeResponse): UserInfo {
  return {
    id: me.id,
    email: me.email,
    displayName: me.display_name,
    operationRole: me.operation_role,
    panelRole: me.panel_role,
  };
}
