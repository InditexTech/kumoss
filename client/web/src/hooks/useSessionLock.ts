// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect } from "react";
import { useSession } from "@/contexts/SessionContext";
import { checkApplyAllowed } from "@/services/core/sessions";

const LOCK_POLL_MS = 20_000;

export function useRefreshSessionLock(): () => Promise<boolean> {
  const { session, updateSession } = useSession();
  const { uuid, is_blocked } = session;

  return useCallback(async () => {
    if (!uuid) return !!is_blocked;
    const blocked = !(await checkApplyAllowed(uuid));
    updateSession({ is_blocked: blocked });
    return blocked;
  }, [uuid, is_blocked, updateSession]);
}

export function useWatchSessionLock(enabled: boolean): void {
  const refresh = useRefreshSessionLock();

  useEffect(() => {
    if (!enabled) return;

    const check = () => {
      if (document.visibilityState !== "visible") return;
      refresh().catch(() => undefined);
    };

    const interval = setInterval(check, LOCK_POLL_MS);
    window.addEventListener("focus", check);
    document.addEventListener("visibilitychange", check);
    return () => {
      clearInterval(interval);
      window.removeEventListener("focus", check);
      document.removeEventListener("visibilitychange", check);
    };
  }, [enabled, refresh]);
}
