import type { UserInfo } from "@/types";

const STORAGE_KEY = "nebula_auth_user";

export function getStoredUser(): UserInfo | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as UserInfo) : null;
  } catch {
    return null;
  }
}

export function storeUser(user: UserInfo): void {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(user));
}

export function clearUser(): void {
  sessionStorage.removeItem(STORAGE_KEY);
}

export function createUserInfo(
  email: string,
  name?: string,
  roles: string[] = [],
): UserInfo {
  return {
    username: email,
    name: name ?? email.split("@")[0],
    homeAccountId: "local",
    environment: "local",
    tenantId: "local",
    localAccountId: "local",
    roles,
  };
}
