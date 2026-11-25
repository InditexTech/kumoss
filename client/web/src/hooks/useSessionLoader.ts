// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useEffect, useRef } from "react";
import { useSession } from "@/contexts/SessionContext";
import {
  resolveSessionOutcome,
  buildSessionPatch,
  buildApplyResults,
  findSessionPr,
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
        } else {
          updateSession(patch);
        }

        // PR state is in-memory only; rebuild it from the session's single
        // PR so a refresh / deep-link keeps the affordances, and clear every
        // field explicitly so a previously loaded session's stale PR doesn't
        // bleed through the shallow merge.
        const pr = findSessionPr(outcome.detail);
        updatePrDetails(
          pr
            ? { number: pr.number, url: pr.url, merged: undefined, lastPrStep: undefined }
            : { number: undefined, url: undefined, merged: undefined, lastPrStep: undefined },
        );
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
