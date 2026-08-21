// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useSession } from "@/contexts/SessionContext";
import { useNotification } from "@/contexts/NotificationContext";
import { invalidateSessionsCache } from "@/services/core/sessionsCache";
import {
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
        // The backend refuses to resume failed sessions (a follow-up POST
        // would 202 and silently never start), so just report and leave.
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

      // Results and rejected rounds both land on the results route; with no
      // artifacts in context (e.g. first-round rejection) it renders the
      // history panel chat-only so the user can reply.
      updateSession({
        ...merged,
        full_history: [
          ...(merged.full_history ?? []),
          { role: "assistant" as const, content: buildAssistantMessage(outcome) },
        ],
      });
      navigate(`/home/results/${outcome.detail.uuid}`, { replace: true });
    },
    [session, updateSession, showNotification, navigate],
  );

  return { handleOutcome } as const;
}
