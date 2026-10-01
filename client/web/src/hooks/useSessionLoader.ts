// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useEffect, useRef } from "react";
import { useSession } from "@/contexts/SessionContext";
import {
  resolveSessionOutcome,
  buildSessionPatch,
  buildApplyResults,
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
  const { session, updateSession, updatePrDetails } = useSession();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fetchedRef = useRef<string | null>(null);

  const alreadyLoaded = !!sessionId && session.uuid === sessionId;

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
          // A rejected round opens no PR of its own, so there is nothing to
          // rebuild; its chat turn (the stored rationale) already arrived
          // with `patch.history`.
          updateSession(patch);
        } else {
          updateSession(patch);
          // PR state is in-memory only; rebuild it from the round so a
          // refresh keeps the View PR / Continue with PR affordances.
          const lastRound =
            outcome.detail.rounds[outcome.detail.rounds.length - 1];
          const pr =
            lastRound?.pull_requests[lastRound.pull_requests.length - 1];
          if (pr) updatePrDetails({ number: pr.number, url: pr.url });
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
  }, [sessionId, alreadyLoaded, updateSession, updatePrDetails]);

  return {
    loading,
    error,
    ready: alreadyLoaded || (!!fetchedRef.current && !loading && !error),
  };
}
