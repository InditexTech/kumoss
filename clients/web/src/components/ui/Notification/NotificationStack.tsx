// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useNotification } from "@/contexts/NotificationContext";
import Notification from "./Notification";
import styles from "./Notification.module.css";

export default function NotificationStack() {
  const { notifications, dismissNotification } = useNotification();

  if (notifications.length === 0) return null;

  return (
    <div className={styles.stack}>
      {notifications.map((n) => (
        <Notification key={n.id} data={n} onDismiss={dismissNotification} />
      ))}
    </div>
  );
}
