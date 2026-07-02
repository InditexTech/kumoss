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
