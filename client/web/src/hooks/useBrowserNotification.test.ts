// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useBrowserNotification } from "./useBrowserNotification";

const mockClose = vi.fn();

interface MockInstance {
  onclick: (() => void) | null;
  close: () => void;
  title: string;
  options: NotificationOptions | undefined;
}

function installNotificationMock(permission: NotificationPermission) {
  const instances: MockInstance[] = [];

  function NotificationMock(
    this: MockInstance,
    title: string,
    options?: NotificationOptions,
  ) {
    this.onclick = null;
    this.close = mockClose;
    this.title = title;
    this.options = options;
    instances.push(this);
  }

  Object.defineProperty(NotificationMock, "permission", {
    get: () => permission,
    configurable: true,
  });

  NotificationMock.requestPermission = vi.fn().mockResolvedValue("granted");

  Object.defineProperty(globalThis, "Notification", {
    value: NotificationMock,
    writable: true,
    configurable: true,
  });

  return { instances };
}

function setDocumentHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", {
    value: hidden,
    writable: true,
    configurable: true,
  });
}

describe("useBrowserNotification", () => {
  const originalNotification = globalThis.Notification;

  beforeEach(() => {
    vi.clearAllMocks();
    setDocumentHidden(false);
  });

  afterEach(() => {
    Object.defineProperty(globalThis, "Notification", {
      value: originalNotification,
      writable: true,
      configurable: true,
    });
  });

  it("returns current permission on mount", () => {
    installNotificationMock("granted");
    const { result } = renderHook(() => useBrowserNotification());
    expect(result.current.permission).toBe("granted");
  });

  it("does nothing when tab is visible", async () => {
    const { instances } = installNotificationMock("granted");
    setDocumentHidden(false);

    const { result } = renderHook(() => useBrowserNotification());
    await act(() => result.current.notifyIfHidden("Test"));

    expect(instances).toHaveLength(0);
  });

  it("fires notification when tab is hidden and permission granted", async () => {
    const { instances } = installNotificationMock("granted");
    setDocumentHidden(true);

    const { result } = renderHook(() => useBrowserNotification());
    await act(() =>
      result.current.notifyIfHidden("Done", { body: "Ready" }),
    );

    expect(instances).toHaveLength(1);
    expect(instances[0].title).toBe("Done");
    expect(instances[0].options).toEqual({ body: "Ready" });
  });

  it("does nothing when permission is default (not yet granted)", async () => {
    const { instances } = installNotificationMock("default");
    setDocumentHidden(true);

    const { result } = renderHook(() => useBrowserNotification());
    await act(() => result.current.notifyIfHidden("Test"));

    expect(instances).toHaveLength(0);
  });

  it("does nothing when permission is denied", async () => {
    installNotificationMock("denied");
    setDocumentHidden(true);

    const { result } = renderHook(() => useBrowserNotification());
    await act(() => result.current.notifyIfHidden("Test"));
  });

  it("focuses window on notification click", async () => {
    const { instances } = installNotificationMock("granted");
    setDocumentHidden(true);
    const focusSpy = vi.spyOn(window, "focus").mockImplementation(() => {});

    const { result } = renderHook(() => useBrowserNotification());
    await act(() => result.current.notifyIfHidden("Click me"));

    instances[0].onclick?.();
    expect(focusSpy).toHaveBeenCalled();
    expect(mockClose).toHaveBeenCalled();

    focusSpy.mockRestore();
  });

  it("is a no-op when Notification API is unavailable", async () => {
    Object.defineProperty(globalThis, "Notification", {
      value: undefined,
      writable: true,
      configurable: true,
    });

    const { result } = renderHook(() => useBrowserNotification());
    expect(result.current.permission).toBe("default");
    await act(() => result.current.notifyIfHidden("Test"));
  });
});
