// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import React, {
  createContext,
  useContext,
  useState,
  useMemo,
  useCallback,
} from "react";
import type { Session, PrDetails } from "@/types/ui";

interface SessionContextValue {
  session: Session;
  updateSession: (patch: Partial<Session>) => void;
  /**
   * Clears session and PR state. Called from the header logo so that going
   * home also discards the information collected so far.
   */
  resetSession: () => void;
  /**
   * Monotonic counter bumped by every `resetSession()` call. Consumers that
   * own state outside this provider — the home wizard's steps and collected
   * data — watch it to learn that a clear was requested elsewhere in the tree.
   */
  resetNonce: number;
  prDetails: PrDetails;
  updatePrDetails: (patch: Partial<PrDetails>) => void;
}

const SessionContext = createContext<SessionContextValue | undefined>(
  undefined,
);

const initialSession: Session = {};

const initialPrDetails: PrDetails = {};

export function SessionProvider({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const [session, setSession] = useState<Session>(initialSession);
  const [prDetails, setPrDetails] = useState<PrDetails>(initialPrDetails);
  const [resetNonce, setResetNonce] = useState(0);

  const updateSession = useCallback((patch: Partial<Session>) => {
    setSession((prev: Session) => ({ ...prev, ...patch }));
  }, []);

  const updatePrDetails = useCallback((patch: Partial<PrDetails>) => {
    setPrDetails((prev: PrDetails) => ({ ...prev, ...patch }));
  }, []);

  const resetSession = useCallback(() => {
    setSession(initialSession);
    setPrDetails(initialPrDetails);
    setResetNonce((n) => n + 1);
  }, []);

  const value = useMemo(
    () => ({
      session,
      updateSession,
      resetSession,
      resetNonce,
      prDetails,
      updatePrDetails,
    }),
    [
      session,
      updateSession,
      resetSession,
      resetNonce,
      prDetails,
      updatePrDetails,
    ],
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within SessionProvider");
  return ctx;
}
