// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useEffect, useRef } from "react";
import { useSession } from "@/contexts/SessionContext";
import {
  resolveSessionOutcome,
  buildSessionPatch,
  buildApplyResults,
  buildAssistantMessage,
} from "@/services/workflows/session_outcome";

interface SessionLoaderResult {
  loading: boolean;
  error: string | null;
  ready: boolean;
}

/** Rebuilds the session context for deep links / refreshes of
 *  /home/results/{id} and /home/apply-results/{id}. */
export function useSessionLoader(
  sessionId: string | undefined,
): SessionLoaderResult {
  const { session, updateSession } = useSession();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fetchedRef = useRef<string | null>(null);

  const alreadyLoaded = !!sessionId && session.session_id === sessionId;

  useEffect(() => {
    if (!sessionId || alreadyLoaded || fetchedRef.current === sessionId) return;

    let cancelled = false;
    setLoading(true);
    setError(null);

    resolveSessionOutcome(sessionId)
      .then((outcome) => {
        if (cancelled) return;

        if (outcome.kind === "failed") {
          setError(outcome.message);
          setLoading(false);
          return;
        }

        fetchedRef.current = sessionId;
        const patch = buildSessionPatch(outcome);

        if (outcome.kind === "apply-results") {
          updateSession({ ...patch, applyResults: buildApplyResults(outcome) });
        } else if (outcome.kind === "rejected") {
          updateSession({
            ...patch,
            full_history: [
              ...(patch.full_history ?? []),
              {
                role: "assistant" as const,
                content: buildAssistantMessage(outcome),
              },
            ],
          });
        } else {
          updateSession(patch);
        }
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(
          err instanceof Error ? err.message : "Failed to load session",
        );
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [sessionId, alreadyLoaded, updateSession]);

  return {
    loading,
    error,
    ready: alreadyLoaded || (!!fetchedRef.current && !loading && !error),
  };
}
