import { useEffect, useRef, useState } from "react";
import { isAllowedUrl } from "@/utils/sanitize";
import { Fade } from "@mui/material";
import { NOTIFICATION_TIMEOUT_MS } from "@/constants";
import type { NotificationData } from "@/types/ui";
import styles from "./Notification.module.css";

interface Props {
  data: NotificationData;
  onDismiss: (id: string) => void;
}

const iconColor = (type: NotificationData["type"]) =>
  type === "success" ? "black" : "white";

function ExclamationIcon({ color }: { color: string }) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <path d="M7.52941 8.94118V3.29412H8.47059V8.94118H7.52941Z" fill={color} />
      <path
        d="M8.70588 10.8235C8.70588 11.2134 8.38985 11.5294 8 11.5294C7.61015 11.5294 7.29412 11.2134 7.29412 10.8235C7.29412 10.4337 7.61015 10.1176 8 10.1176C8.38985 10.1176 8.70588 10.4337 8.70588 10.8235Z"
        fill={color}
      />
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M0 8C0 3.58172 3.58172 0 8 0C12.4183 0 16 3.58172 16 8C16 12.4183 12.4183 16 8 16C3.58172 16 0 12.4183 0 8ZM8 0.941176C4.10152 0.941176 0.941176 4.10152 0.941176 8C0.941176 11.8985 4.10152 15.0588 8 15.0588C11.8985 15.0588 15.0588 11.8985 15.0588 8C15.0588 4.10152 11.8985 0.941176 8 0.941176Z"
        fill={color}
      />
    </svg>
  );
}

function CheckmarkIcon({ color }: { color: string }) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="7.5" stroke={color} />
      <path
        d="M11.5 5.5L7 11L4.5 8.5"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CloseIcon({ color }: { color: string }) {
  return (
    <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
      <path
        d="M3.22887 3.855L0 7.08387L0.626131 7.71L3.855 4.48113L7.08387 7.71L7.71 7.08387L4.48113 3.855L7.71 0.626131L7.08387 0L3.855 3.22887L0.626131 0L0 0.626131L3.22887 3.855Z"
        fill={color}
      />
    </svg>
  );
}

export default function Notification({ data, onDismiss }: Props) {
  const color = iconColor(data.type);
  const isUrgent = data.type === "failure" || data.type === "warning";
  const autoDismiss = data.type !== "failure";

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const remainingRef = useRef(NOTIFICATION_TIMEOUT_MS);
  const startedAtRef = useRef(Date.now());
  const [hovered, setHovered] = useState(false);

  useEffect(() => {
    if (!autoDismiss) return;

    if (hovered) {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
        remainingRef.current -= Date.now() - startedAtRef.current;
      }
      return;
    }

    startedAtRef.current = Date.now();
    timerRef.current = setTimeout(
      () => onDismiss(data.id),
      remainingRef.current,
    );
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [autoDismiss, hovered, data.id, onDismiss]);

  const handleActionClick = () => {
    if (data.action?.onClick) {
      data.action.onClick();
    } else if (data.action?.href && isAllowedUrl(data.action.href)) {
      window.open(data.action.href, "_blank", "noopener,noreferrer");
    }
  };

  return (
    <Fade in timeout={1000}>
      <div
        className={`${styles.notification} ${styles[data.type]}`}
        role={isUrgent ? "alert" : undefined}
        aria-live={isUrgent ? undefined : "polite"}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        <div className={styles.icon}>
          {data.type === "success" ? (
            <CheckmarkIcon color={color} />
          ) : (
            <ExclamationIcon color={color} />
          )}
        </div>

        <div className={styles.content}>
          <p className={styles.message}>
            {data.message}
            {data.action && (
              <>
                {" "}
                <a className={styles.action} onClick={handleActionClick}>
                  {data.action.label}
                </a>
              </>
            )}
          </p>
        </div>

        <button
          type="button"
          className={styles.close}
          onClick={() => onDismiss(data.id)}
          aria-label="Dismiss notification"
        >
          <CloseIcon color={color} />
        </button>
      </div>
    </Fade>
  );
}
