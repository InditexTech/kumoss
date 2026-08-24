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
  // Resets session and PR state for starting a new action from chat (same or different mode).
  // Not wired up yet — will be connected when the "new action" chat flow is implemented.
  resetSession: () => void;
  prDetails: PrDetails;
  updatePrDetails: (patch: Partial<PrDetails>) => void;
}

const SessionContext = createContext<SessionContextValue | undefined>(
  undefined,
);

const initialSession: Session = {
  session_id: undefined,
  cloud: undefined,
  project: undefined,
  environment: undefined,
  uniqueRepositoryName: undefined,
  branchName: undefined,
  firstQuery: undefined,
  validatorProvider: undefined,
  terraform_targets: undefined,
  terraform_report: undefined,
  userQueries: [],
  full_history: undefined,
  apply_allowed: undefined,
  current_status: undefined,
};

const initialPrDetails: PrDetails = {
  prUrl: undefined,
  id: undefined,
};

export function SessionProvider({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const [session, setSession] = useState<Session>(initialSession);
  const [prDetails, setPrDetails] = useState<PrDetails>(initialPrDetails);

  const updateSession = useCallback((patch: Partial<Session>) => {
    setSession((prev: Session) => ({ ...prev, ...patch }));
  }, []);

  const updatePrDetails = useCallback((patch: Partial<PrDetails>) => {
    setPrDetails((prev: PrDetails) => ({ ...prev, ...patch }));
  }, []);

  const resetSession = useCallback(() => {
    setSession(initialSession);
    setPrDetails(initialPrDetails);
  }, []);

  const value = useMemo(
    () => ({ session, updateSession, resetSession, prDetails, updatePrDetails }),
    [session, updateSession, resetSession, prDetails, updatePrDetails],
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
