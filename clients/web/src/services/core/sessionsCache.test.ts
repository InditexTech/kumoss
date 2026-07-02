import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  getCachedSessions,
  setCachedSessions,
  invalidateSessionsCache,
} from "./sessionsCache";
import type { UserSessionInfo } from "@/types/api";

const makeFakeSession = (id: string): UserSessionInfo =>
  ({
    session_id: id,
    user_id: "user@test.com",
    repo_uri: "https://repo.example.com",
    cloud_provider: "azure",
    environment: "dev",
    branch_name: "main",
    status: "completed",
    in_flight: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  }) as UserSessionInfo;

describe("sessionsCache", () => {
  beforeEach(() => {
    invalidateSessionsCache();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns null when no cache exists", () => {
    expect(getCachedSessions()).toBeNull();
  });

  it("returns cached data within TTL", () => {
    const sessions = [makeFakeSession("s1"), makeFakeSession("s2")];
    setCachedSessions(sessions, 42);

    const result = getCachedSessions();
    expect(result).not.toBeNull();
    expect(result!.sessions).toEqual(sessions);
    expect(result!.total).toBe(42);
  });

  it("returns null after TTL expires", () => {
    setCachedSessions([makeFakeSession("s1")], 1);

    vi.advanceTimersByTime(30_001);

    expect(getCachedSessions()).toBeNull();
  });

  it("returns data just before TTL expires", () => {
    setCachedSessions([makeFakeSession("s1")], 1);

    vi.advanceTimersByTime(29_999);

    expect(getCachedSessions()).not.toBeNull();
  });

  it("clears cache on invalidate", () => {
    setCachedSessions([makeFakeSession("s1")], 1);
    expect(getCachedSessions()).not.toBeNull();

    invalidateSessionsCache();
    expect(getCachedSessions()).toBeNull();
  });

  it("overwrites previous cache on set", () => {
    setCachedSessions([makeFakeSession("s1")], 1);
    setCachedSessions([makeFakeSession("s2"), makeFakeSession("s3")], 10);

    const result = getCachedSessions();
    expect(result!.sessions).toHaveLength(2);
    expect(result!.sessions[0].session_id).toBe("s2");
    expect(result!.total).toBe(10);
  });
});
