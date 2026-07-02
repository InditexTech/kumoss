import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import type { UserInfo } from "@/types";
import {
  getStoredUser,
  storeUser,
  clearUser,
  createUserInfo,
} from "@/services/auth";
import { apiFetch } from "@/services/api";
import type { UserMeResponse } from "@/types/api";

interface AuthContextValue {
  user: UserInfo | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  isAuthenticated: boolean;
  isAdmin: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: Readonly<{ children: ReactNode }>) {
  const [user, setUser] = useState<UserInfo | null>(getStoredUser);

  const isAuthenticated = user !== null;
  const isAdmin = user?.roles?.includes("admin") ?? false;

  const login = useCallback(async (_email: string, _password: string) => {
    const newUser = createUserInfo(_email);
    storeUser(newUser);
    setUser(newUser);

    try {
      const me = await apiFetch<UserMeResponse>("/api/v1/users/me");
      const enriched = createUserInfo(_email, newUser.name, me.roles);
      storeUser(enriched);
      setUser(enriched);
    } catch {
      // roles unavailable — keep user with empty roles
    }
  }, []);

  const logout = useCallback(() => {
    clearUser();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, login, logout, isAuthenticated, isAdmin }),
    [user, login, logout, isAuthenticated, isAdmin],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
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
