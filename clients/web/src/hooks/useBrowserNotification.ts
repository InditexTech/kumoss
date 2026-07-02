import { useState, useCallback, useEffect } from "react";

const isSupported = () => typeof globalThis.Notification !== "undefined";

export function useBrowserNotification() {
  const [permission, setPermission] = useState<NotificationPermission>(
    isSupported() ? Notification.permission : "default",
  );

  useEffect(() => {
    if (isSupported()) setPermission(Notification.permission);
  }, []);

  const requestPermission = useCallback(async () => {
    if (!isSupported()) return "default" as NotificationPermission;
    const result = await Notification.requestPermission();
    setPermission(result);
    return result;
  }, []);

  const notifyIfHidden = useCallback(
    (title: string, options?: NotificationOptions) => {
      if (!isSupported() || !document.hidden) return;
      if (Notification.permission !== "granted") return;

      const notification = new Notification(title, options);
      notification.onclick = () => {
        window.focus();
        notification.close();
      };
    },
    [],
  );

  return { notifyIfHidden, requestPermission, permission } as const;
}
