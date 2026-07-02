import { describe, it, expect, beforeEach, vi } from "vitest";

describe("localStorage wrappers", () => {
  let storage: typeof import("./storage");

  beforeEach(async () => {
    localStorage.clear();
    vi.resetModules();
    storage = await import("./storage");
  });

  it("sets and gets a string value", () => {
    storage.setLocalItem("key", "value");
    expect(storage.getLocalItem("key")).toBe("value");
  });

  it("returns null for a missing key", () => {
    expect(storage.getLocalItem("nonexistent")).toBeNull();
  });

  it("overwrites an existing value", () => {
    storage.setLocalItem("key", "first");
    storage.setLocalItem("key", "second");
    expect(storage.getLocalItem("key")).toBe("second");
  });
});

describe("sessionStorage wrappers", () => {
  let storage: typeof import("./storage");

  beforeEach(async () => {
    sessionStorage.clear();
    vi.resetModules();
    storage = await import("./storage");
  });

  it("sets and gets a string value", () => {
    storage.setSessionItem("key", "value");
    expect(storage.getSessionItem("key")).toBe("value");
  });

  it("returns null for a missing key", () => {
    expect(storage.getSessionItem("nonexistent")).toBeNull();
  });

});

describe("unavailable storage handling", () => {
  let storage: typeof import("./storage");

  beforeEach(async () => {
    vi.resetModules();
    storage = await import("./storage");
  });

  it("getLocalItem returns null when localStorage.getItem throws", () => {
    const spy = vi
      .spyOn(Storage.prototype, "getItem")
      .mockImplementation(() => {
        throw new DOMException("SecurityError");
      });
    expect(storage.getLocalItem("key")).toBeNull();
    spy.mockRestore();
  });

  it("setLocalItem does not throw when localStorage.setItem throws", () => {
    const spy = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new DOMException("QuotaExceededError");
      });
    expect(() => storage.setLocalItem("key", "value")).not.toThrow();
    spy.mockRestore();
  });
});
