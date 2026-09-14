// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useEffect, useRef } from "react";
import { useSession } from "@/contexts/SessionContext";
import { TERMINAL_STATUSES } from "@/types/api";
import type { ResumeTarget } from "@/types/ui";
import {
  resolveSessionOutcome,
  buildSessionPatch,
  buildApplyResults,
  buildAssistantMessage,
  appendAssistantMessage,
  isApplyRound,
} from "@/services/workflows/session_outcome";

interface SessionLoaderResult {
  loading: boolean;
  error: string | null;
  ready: boolean;
  /** Set when the session has no results yet because it is still running. */
  inProgress: ResumeTarget | null;
}

/** Rebuilds the session context for deep links / refreshes of
 *  /home/results/{id} and /home/apply-results/{id}. */
export function useSessionLoader(
  sessionId: string | undefined,
): SessionLoaderResult {
  const { session, updateSession, updatePrDetails } = useSession();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inProgress, setInProgress] = useState<ResumeTarget | null>(null);
  const fetchedRef = useRef<string | null>(null);

  // A session the context still holds as running has to be re-resolved: the
  // sessions-table reload patches it in before navigating, and its stored
  // status is by definition not the final one.
  const contextIsRunning =
    !!session.current_status &&
    !TERMINAL_STATUSES.includes(session.current_status);
  const alreadyLoaded =
    !!sessionId && session.uuid === sessionId && !contextIsRunning;

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

        if (outcome.kind === "in-progress") {
          // No artifacts exist yet. Rehydrate the facts so the resumed run has
          // its session context, and hand the round back for the caller to
          // reattach to; `ready` stays false so no empty result is rendered.
          updateSession(patch);
          setInProgress({
            sessionId,
            isApply: isApplyRound(outcome.round),
          });
          setLoading(false);
          return;
        }

        if (outcome.kind === "apply-results") {
          updateSession({ ...patch, applyResults: buildApplyResults(outcome) });
        } else if (outcome.kind === "rejected") {
          updateSession({
            ...patch,
            history: appendAssistantMessage(
              patch.history,
              buildAssistantMessage(outcome),
            ),
          });
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
    ready:
      !inProgress &&
      (alreadyLoaded || (!!fetchedRef.current && !loading && !error)),
    inProgress,
  };
}
