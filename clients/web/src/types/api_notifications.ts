export enum NotificationSeverity {
  INFO = "info",
  WARNING = "warning",
  ERROR = "error",
  CRITICAL = "critical",
}

export interface NotificationLink {
  label: string;
  url: string;
}

export interface Notification {
  kind: string;
  severity: NotificationSeverity;
  subject: string;
  body: string;
  audience?: string[];
  links?: NotificationLink[];
  context?: { [key: string]: unknown };
}

export interface NotificationAccepted {
  delivery_id: string;
}
