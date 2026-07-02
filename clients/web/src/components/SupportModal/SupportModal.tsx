import { useState, useCallback } from "react";
import { ButtonBase } from "@mui/material";
import { useAuth } from "@/contexts/AuthContext";
import { useSession } from "@/contexts/SessionContext";
import { useNotification } from "@/contexts/NotificationContext";
import { sendNotification } from "@/services/notifications/notification";
import { NotificationSeverity } from "@/types/api_notifications";
import { containsHtml } from "@/utils/sanitize";
import { STRINGS } from "@/constants/strings";
import { Modal } from "@/components/ui";
import styles from "./SupportModal.module.css";

const MAX_LENGTH = 500;

interface SupportModalProps {
  onClose: () => void;
}

export default function SupportModal({ onClose }: SupportModalProps) {
  const { user } = useAuth();
  const { session } = useSession();
  const { showNotification } = useNotification();
  const [question, setQuestion] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const validate = useCallback((text: string): string | null => {
    const trimmed = text.trim();
    if (!trimmed) return STRINGS.supportModal.emptyError;
    if (trimmed.length > MAX_LENGTH) return STRINGS.supportModal.maxLengthError;
    if (containsHtml(trimmed)) return STRINGS.supportModal.htmlError;
    return null;
  }, []);

  const handleSubmit = useCallback(async () => {
    const validationError = validate(question);
    if (validationError) {
      setError(validationError);
      return;
    }

    setIsSubmitting(true);
    try {
      await sendNotification({
        kind: "support.user_question",
        severity: NotificationSeverity.INFO,
        subject: `Support request from ${user?.username ?? "unknown"}`,
        body: question.trim(),
        audience: user?.username ? [user.username] : [],
        context: {
          user_email: user?.username ?? "",
          user_name: user?.name ?? "",
          cloud: session.cloud ?? null,
          project: session.project ?? null,
          environment: session.environment ?? null,
        },
      });

      showNotification("success", STRINGS.supportModal.success);
      onClose();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      showNotification("failure", message);
    } finally {
      setIsSubmitting(false);
    }
  }, [question, validate, user, session, showNotification, onClose]);

  return (
    <Modal title={STRINGS.supportModal.title} onClose={onClose}>
      <div className={styles.content}>
        <p className={styles.description}>
          {STRINGS.supportModal.description}
        </p>
        <textarea
          className={styles.textArea}
          value={question}
          onChange={(e) => {
            setQuestion(e.target.value);
            setError(null);
          }}
          placeholder={STRINGS.supportModal.placeholder}
          maxLength={MAX_LENGTH}
        />
        <div className={styles.footer}>
          {error && <p className={styles.error}>{error}</p>}
          <span className={styles.charCount}>
            {question.length}/{MAX_LENGTH}
          </span>
          <ButtonBase
            className={styles.submitButton}
            onClick={handleSubmit}
            disabled={isSubmitting || !question.trim()}
          >
            {isSubmitting
              ? STRINGS.supportModal.sending
              : STRINGS.supportModal.send}
          </ButtonBase>
        </div>
      </div>
    </Modal>
  );
}
