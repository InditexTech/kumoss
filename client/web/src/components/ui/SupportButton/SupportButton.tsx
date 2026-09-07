// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useAuth } from "@/contexts/AuthContext";
import { useState, useEffect, useRef, useCallback } from "react";
import { ButtonBase, Tooltip } from "@mui/material";
import ChatBubbleOutlineIcon from "@mui/icons-material/ChatBubbleOutline";
import { useSession } from "@/contexts/SessionContext";
import { useNotification } from "@/contexts/NotificationContext";
import { checkApplyAllowed } from "@/services/core/sessions";
import { getSessionItem, setSessionItem } from "@/services";
import { getApiErrorMessage } from "@/services/api";
import { sendNotification } from "@/services/notifications/notification";
import {
  buildSupportContext,
  buildSupportLinks,
  buildSupportSubject,
} from "@/services/notifications/support";
import { NotificationSeverity } from "@/types/api_notifications";
import { STRINGS } from "@/constants/strings";
import styles from "./SupportButton.module.css";

interface SupportContext {
  user: { name: string; email: string } | null;
  cloud?: string;
  project?: string;
  environment?: string;
  query?: string;
  timestamp: string;
  [key: string]: unknown;
}

interface Props {
  message?: string;
  buttonText?: string;
  context?: Record<string, unknown>;
  onSupportRequest?: (context: SupportContext) => void;
  autoTrigger?: boolean;
  variant?: "text" | "icon";
}

/**
 * "Contact team" entry point used from the results and PR views.
 *
 * Sends a `support.contact_team` notification through the core to the
 * notifications service, carrying the session metadata (session id,
 * request text, cloud/project/environment, PR link, whether the plan has
 * deletes or recreates) so the person answering in Slack can act
 * without asking the user for details.
 */
function SupportButton({
  message,
  buttonText = STRINGS.support.buttonText,
  context = {},
  onSupportRequest,
  autoTrigger = false,
  variant = "text",
}: Props) {
  const { user } = useAuth();
  const { session, prDetails } = useSession();
  const { showNotification } = useNotification();
  const [isLoading, setIsLoading] = useState(false);
  const hasAutoTriggered = useRef(false);

  const handleSupportRequest = useCallback(async () => {
    setIsLoading(true);

    const userInfo = user
      ? { name: user.name || "", email: user.username }
      : null;

    if (!userInfo?.email) {
      alert(STRINGS.support.noEmailError);
      setIsLoading(false);
      return;
    }

    const supportContext: SupportContext = {
      user: userInfo,
      cloud: session.cloud,
      project: session.project,
      environment: session.environment,
      query: session.firstQuery,
      ...context,
      timestamp: new Date().toISOString(),
    };

    if (onSupportRequest) {
      onSupportRequest(supportContext);
      setIsLoading(false);
      return;
    }

    try {
      let hasDeletesOrRecreates: boolean | null = null;
      if (session.session_id) {
        try {
          hasDeletesOrRecreates = !(await checkApplyAllowed(session.session_id));
        } catch {
          // Unknown; the field is dropped by the renderer when null.
        }
      }

      const trigger = autoTrigger && !hasAutoTriggered.current ? "automatic" : "manual";
      const body =
        message ??
        (hasDeletesOrRecreates
          ? "The user asked for help with a plan that deletes or recreates resources."
          : "The user asked for help with this session.");

      await sendNotification({
        kind: "support.contact_team",
        severity: hasDeletesOrRecreates
          ? NotificationSeverity.WARNING
          : NotificationSeverity.INFO,
        subject: buildSupportSubject("Support request", user, session),
        body,
        audience: [userInfo.email],
        links: buildSupportLinks(session, prDetails),
        context: buildSupportContext({
          user,
          session,
          prDetails,
          extra: {
            ...context,
            has_deletes_or_recreates: hasDeletesOrRecreates,
            trigger,
          },
        }),
      });

      showNotification("success", STRINGS.support.groupCreated);
    } catch (error) {
      showNotification(
        "failure",
        `${STRINGS.support.sendFailed} ${getApiErrorMessage(error)}`,
      );
    } finally {
      setIsLoading(false);
    }
  }, [
    user,
    session,
    prDetails,
    context,
    message,
    autoTrigger,
    onSupportRequest,
    showNotification,
  ]);

  useEffect(() => {
    const notificationKey = `nebulaai_notification_sent_${session.session_id}_${prDetails.prUrl || "no_pr"}`;
    const alreadySent = getSessionItem(notificationKey) === "true";

    if (autoTrigger && !hasAutoTriggered.current && !alreadySent && user) {
      hasAutoTriggered.current = true;
      setSessionItem(notificationKey, "true");
      handleSupportRequest();
    }
  }, [
    autoTrigger,
    user,
    session.session_id,
    prDetails.prUrl,
    handleSupportRequest,
  ]);

  if (variant === "icon") {
    return (
      <Tooltip
        title={
          isLoading
            ? STRINGS.support.creatingNotification
            : STRINGS.support.tooltip
        }
        arrow
      >
        <span style={{ display: "inline-flex" }}>
          <ButtonBase
            onClick={handleSupportRequest}
            disabled={isLoading}
            className={styles.iconVariant}
            aria-label="Contact support"
          >
            <ChatBubbleOutlineIcon className={styles.iconVariantIcon} />
          </ButtonBase>
        </span>
      </Tooltip>
    );
  }

  return (
    <div className={styles.supportContainer}>
      <Tooltip
        title={
          isLoading
            ? STRINGS.support.creatingNotification
            : STRINGS.support.tooltip
        }
        arrow
      >
        <span style={{ display: "inline-flex" }}>
          <button
            className={styles.supportButton}
            onClick={handleSupportRequest}
            disabled={isLoading}
          >
            <span className={styles.text}>
              {isLoading ? STRINGS.support.creatingButton : buttonText}
            </span>
          </button>
        </span>
      </Tooltip>
    </div>
  );
}

export default SupportButton;
