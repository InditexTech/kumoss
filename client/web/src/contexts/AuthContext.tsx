// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { useAuth as useOidcAuth } from "react-oidc-context";
import type { UserInfo } from "@/types";
import type { OperationRole, PanelRole } from "@/types/api";
import { isOidcEnabled, toUserInfo } from "@/services/auth";
import type { SigninState } from "@/services/auth";
import { getMe } from "@/services/core/admin";
import { getApiErrorMessage } from "@/services/api";
import { setAccessTokenProvider, UNAUTHORIZED_EVENT } from "@/services/token";

interface AuthContextValue {
  user: UserInfo | null;
  login: () => Promise<void>;
  logout: () => Promise<void>;
  isAuthenticated: boolean;
  isLoading: boolean;
  operationRole: OperationRole | null;
  panelRole: PanelRole | null;
  hasPanelAccess: boolean;
  isPanelAdmin: boolean;
  isAdmin: boolean;
  sessionExpired: boolean;
  authError: string | null;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function buildValue(
  user: UserInfo | null,
  isLoading: boolean,
  login: () => Promise<void>,
  logout: () => Promise<void>,
  sessionExpired: boolean,
  authError: string | null,
): AuthContextValue {
  const isPanelAdmin = user?.panelRole === "admin";
  return {
    user,
    login,
    logout,
    isAuthenticated: user !== null,
    isLoading,
    operationRole: user?.operationRole ?? null,
    panelRole: user?.panelRole ?? null,
    hasPanelAccess: user?.panelRole != null,
    isPanelAdmin,
    isAdmin: isPanelAdmin,
    sessionExpired,
    authError,
  };
}

/** OIDC mode: identity comes from the IdP token, roles from /users/me. */
function OidcAuthProvider({ children }: Readonly<{ children: ReactNode }>) {
  const oidc = useOidcAuth();
  const { signinRedirect, signoutRedirect, removeUser } = oidc;
  const [user, setUser] = useState<UserInfo | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [meError, setMeError] = useState<string | null>(null);
  const tokenRef = useRef<string | null>(null);

  useEffect(() => {
    tokenRef.current = oidc.user?.access_token ?? null;
  }, [oidc.user]);

  useEffect(() => {
    setAccessTokenProvider(() => tokenRef.current);
    return () => setAccessTokenProvider(null);
  }, []);

  useEffect(() => {
    if (!oidc.isAuthenticated) {
      setUser(null);
      return;
    }
    let cancelled = false;
    getMe()
      .then((me) => {
        if (cancelled) return;
        setUser(toUserInfo(me));
        setSessionExpired(false);
        setMeError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        console.error("Failed to resolve the signed-in user:", err);
        setMeError(getApiErrorMessage(err));
        void removeUser();
      });
    return () => {
      cancelled = true;
    };
  }, [oidc.isAuthenticated, removeUser]);

  useEffect(() => {
    const onUnauthorized = () => {
      setSessionExpired(true);
      setUser(null);
      void removeUser();
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [removeUser]);

  const login = useCallback(async () => {
    setSessionExpired(false);
    setMeError(null);
    const path = window.location.pathname + window.location.search;
    const state: SigninState = {
      returnTo: path.startsWith("/auth") ? "/home" : path,
    };
    await signinRedirect({ state });
  }, [signinRedirect]);

  const logout = useCallback(async () => {
    setUser(null);
    try {
      await signoutRedirect();
    } catch {
      // IdP without an end_session_endpoint: local sign-out only.
      await removeUser();
    }
  }, [signoutRedirect, removeUser]);

  const isLoading = oidc.isLoading || (oidc.isAuthenticated && user === null);
  const authError = meError ?? oidc.error?.message ?? null;

  const value = useMemo(
    () => buildValue(user, isLoading, login, logout, sessionExpired, authError),
    [user, isLoading, login, logout, sessionExpired, authError],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/** Dev mode (blank issuer): the backend resolves every call as the dev
 *  admin, so the SPA is authenticated as soon as /users/me answers. */
function DevAuthProvider({ children }: Readonly<{ children: ReactNode }>) {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [authError, setAuthError] = useState<string | null>(null);

  const login = useCallback(async () => {
    setIsLoading(true);
    setAuthError(null);
    try {
      const me = await getMe();
      setUser(toUserInfo(me));
    } catch (err) {
      setUser(null);
      setAuthError(getApiErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void login();
  }, [login]);

  const logout = useCallback(async () => {
    setUser(null);
  }, []);

  const value = useMemo(
    () => buildValue(user, isLoading, login, logout, false, authError),
    [user, isLoading, login, logout, authError],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function AuthProvider({ children }: Readonly<{ children: ReactNode }>) {
  if (isOidcEnabled()) {
    return <OidcAuthProvider>{children}</OidcAuthProvider>;
  }
  return <DevAuthProvider>{children}</DevAuthProvider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function Authenticated({ children }: Readonly<{ children: ReactNode }>) {
  const { user } = useAuth();
  return user ? <>{children}</> : null;
}

export function Unauthenticated({
  children,
}: Readonly<{ children: ReactNode }>) {
  const { user } = useAuth();
  return user ? null : <>{children}</>;
}
