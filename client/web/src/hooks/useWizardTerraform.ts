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
        const sessionId = session.uuid ?? outcome.detail?.uuid;
        if (sessionId && session.applyResults) {
          navigate(`/home/apply-results/${sessionId}`, { replace: true });
        } else if (sessionId && session.code) {
          navigate(`/home/results/${sessionId}`, { replace: true });
        } else {
          navigate("/home", { replace: true });
        }
        return;
      }

      if (outcome.kind === "apply-results") {
        updateSession({
          ...patch,
          applyResults: buildApplyResults(outcome),
        });
        navigate(`/home/apply-results/${outcome.detail.uuid}`, {
          replace: true,
        });
        return;
      }

      // The conversation comes from the backend whole: `patch.history` is
      // `chat_history`, which already carries this round's reply.
      updateSession(patch);
      navigate(`/home/results/${outcome.detail.uuid}`, { replace: true });
    },
    [session, updateSession, showNotification, navigate],
  );

  return { handleOutcome } as const;
}
