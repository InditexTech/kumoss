// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useEffect, useRef } from "react";
import { useSession } from "@/contexts/SessionContext";
import { getSessionData } from "@/services/core/events";

interface SessionLoaderResult {
  loading: boolean;
  error: string | null;
  ready: boolean;
}

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

    getSessionData(sessionId)
      .then((payload) => {
        if (cancelled) return;
        fetchedRef.current = sessionId;
        updateSession({
          session_id: payload.id,
          cloud: payload.cloud,
          project: payload.project,
          environment: payload.environment,
          branchName: payload.branch_name,
          terraform_targets: payload.terraform_targets ?? undefined,
          terraform_report: payload.terraform_report ?? undefined,
          full_history: payload.full_history,
          pipeline_url: payload.pipeline_url ?? undefined,
          apply_allowed: payload.apply_allowed,
        });
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
