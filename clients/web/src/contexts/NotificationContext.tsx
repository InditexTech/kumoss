import React, { createContext, useCallback, useContext, useState, useMemo } from "react";
import type { NotificationType, NotificationData, NotificationAction } from "@/types/ui";
import { NotificationStack } from "@/components/ui";

const MAX_NOTIFICATIONS = 3;

interface NotificationContextValue {
  notifications: NotificationData[];
  showNotification: (
    type: NotificationType,
    message: string,
    options?: { action?: NotificationAction },
  ) => void;
  dismissNotification: (id: string) => void;
}

const NotificationContext = createContext<NotificationContextValue | undefined>(undefined);

export const useNotification = () => {
  const ctx = useContext(NotificationContext);
  if (!ctx) throw new Error("useNotification must be used within NotificationProvider");
  return ctx;
};

export const NotificationProvider = ({ children }: { children: React.ReactNode }) => {
  const [notifications, setNotifications] = useState<NotificationData[]>([]);

  const dismissNotification = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  }, []);

  const showNotification = useCallback(
    (type: NotificationType, message: string, options?: { action?: NotificationAction }) => {
      const entry: NotificationData = {
        id: crypto.randomUUID(),
        type,
        message,
        action: options?.action,
      };
      setNotifications((prev) => {
        const next = [...prev, entry];
        return next.length > MAX_NOTIFICATIONS ? next.slice(-MAX_NOTIFICATIONS) : next;
      });
    },
    [],
  );

  const value = useMemo(
    () => ({ notifications, showNotification, dismissNotification }),
    [notifications, showNotification, dismissNotification],
  );

  return (
    <NotificationContext.Provider value={value}>
      {children}
      <NotificationStack />
    </NotificationContext.Provider>
  );
};
