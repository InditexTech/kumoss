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

function SupportButton({
  message: _message,
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
    console.log("Opening Nebula AI Support");

    const userInfo = user
      ? { name: user.displayName ?? "", email: user.email ?? "" }
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

    console.log("Support Context:", supportContext);

    if (onSupportRequest) {
      onSupportRequest(supportContext);
      setIsLoading(false);
      return;
    }

    try {
      let hasDeletesOrRecreates = false;
      if (session.session_id) {
        try {
          const allowed = await checkApplyAllowed(session.session_id);
          hasDeletesOrRecreates = !allowed;
        } catch {
          // ignore — default to false
        }
      }

      const payload: Record<string, unknown> = {
        user_mail: userInfo.email,
        user_name: userInfo.name,
        cloud_provider: session.cloud || "N/A",
        dcap_project: session.project || "N/A",
        environment: session.environment || "N/A",
        session_id: session.session_id || null,
        first_query: session.firstQuery || "No query provided",
        has_deletes_or_recreates: hasDeletesOrRecreates,
      };

      if (prDetails.prUrl) {
        payload.pull_request_link = prDetails.prUrl;
      }

      showNotification("success", STRINGS.support.groupCreated);
    } catch (error) {
      console.error("Error sending Teams support request:", error);
      const errorMessage =
        error instanceof Error ? error.message : String(error);
      showNotification("failure", `Failed to create Teams support group. ${errorMessage}` );
    } finally {
      setIsLoading(false);
    }
  }, [user, session, prDetails, context, onSupportRequest, showNotification]);

  useEffect(() => {
    const notificationKey = `nebulaai_notification_sent_${session.session_id}_${prDetails.prUrl || "no_pr"}`;
    const alreadySent = getSessionItem(notificationKey) === "true";

    if (autoTrigger && !hasAutoTriggered.current && !alreadySent && user) {
      hasAutoTriggered.current = true;
      setSessionItem(notificationKey, "true");
      console.log("Auto-triggering Nebula AI support notification...");
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
            aria-label="Send Teams notification"
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
