// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useSession } from "@/contexts/SessionContext";
import { useNotification } from "@/contexts/NotificationContext";
import { invalidateSessionsCache } from "@/services/core/sessionsCache";
import {
  appendAssistantMessage,
  buildApplyResults,
  buildAssistantMessage,
  buildSessionPatch,
  type SessionOutcome,
} from "@/services/workflows/session_outcome";

export function useWizardTerraform() {
  const { session, updateSession } = useSession();
  const { showNotification } = useNotification();
  const navigate = useNavigate();

  const handleOutcome = useCallback(
    (outcome: SessionOutcome) => {
      invalidateSessionsCache();
      const patch = buildSessionPatch(outcome);

      if (outcome.kind === "failed") {
        updateSession(patch);
        showNotification("failure", outcome.message);
        const sessionId = session.session_id ?? outcome.detail?.uuid;
        if (sessionId && session.applyResults) {
          navigate(`/home/apply-results/${sessionId}`, { replace: true });
        } else if (sessionId && session.code) {
          navigate(`/home/results/${sessionId}`, { replace: true });
        } else {
          navigate("/home", { replace: true });
        }
        return;
      }

      const merged = {
        ...patch,
        project: session.project ?? patch.project,
        environment: session.environment ?? patch.environment,
      };

      if (outcome.kind === "apply-results") {
        updateSession({
          ...merged,
          applyResults: buildApplyResults(outcome),
        });
        navigate(`/home/apply-results/${outcome.detail.uuid}`, {
          replace: true,
        });
        return;
      }

      updateSession({
        ...merged,
        full_history: appendAssistantMessage(
          merged.full_history,
          buildAssistantMessage(outcome),
        ),
      });
      navigate(`/home/results/${outcome.detail.uuid}`, { replace: true });
    },
    [session, updateSession, showNotification, navigate],
  );

  return { handleOutcome } as const;
}
