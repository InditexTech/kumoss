// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * HOOK: useInitialInformation
 *
 * A hook is the React bridge for a workflow. It owns all the state
 * (loading, error, result) and exposes an action function that
 * components call. Internally it delegates to the workflow.
 *
 * Anatomy of a hook in this codebase:
 *   1. Define a State type (idle | loading | success | error).
 *   2. Use useRef for the AbortController so you can cancel on unmount.
 *   3. Expose a single `run(...)` function that triggers the workflow.
 *   4. Return the state + the action — nothing else.
 *
 * Why useReducer instead of multiple useState?
 *   When you have several related fields (loading, error, data) that
 *   always change together, useReducer prevents impossible intermediate
 *   states (e.g., loading=true AND error set). A single dispatch
 *   atomically moves from one valid state to the next.
 */

import { useReducer, useRef, useCallback, useEffect } from "react";
import {
  runInitialInfoWorkflow,
  type InitialInfoParams,
  type InitialInfoResult,
} from "@/services/workflows/initial_information";
import { ApiError } from "@/services/api";

// ─── State machine ─────────────────────────────────────────────
//
// The hook models four mutually exclusive states.
// Components can `switch (state.status)` to render the right UI.

type State =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; data: Extract<InitialInfoResult, { ok: true }> }
  | { status: "error"; message: string; failedStep?: string };

type Action =
  | { type: "START" }
  | { type: "SUCCESS"; data: Extract<InitialInfoResult, { ok: true }> }
  | { type: "BUSINESS_ERROR"; message: string; failedStep: string }
  | { type: "NETWORK_ERROR"; message: string }
  | { type: "RESET" };

function reducer(_state: State, action: Action): State {
  switch (action.type) {
    case "START":
      return { status: "loading" };
    case "SUCCESS":
      return { status: "success", data: action.data };
    case "BUSINESS_ERROR":
      return {
        status: "error",
        message: action.message,
        failedStep: action.failedStep,
      };
    case "NETWORK_ERROR":
      return { status: "error", message: action.message };
    case "RESET":
      return { status: "idle" };
  }
}

// ─── The hook ──────────────────────────────────────────────────

export function useInitialInformation() {
  const [state, dispatch] = useReducer(reducer, { status: "idle" });

  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  // ── The action your component calls ──────────────────────────
  const run = useCallback(async (params: InitialInfoParams) => {
    abortRef.current?.abort();
    abortRef.current = new AbortController();

    dispatch({ type: "START" });

    try {
      const result = await runInitialInfoWorkflow(
        params,
        abortRef.current.signal,
      );

      if (result.ok) {
        dispatch({ type: "SUCCESS", data: result });
      } else {
        // The workflow returned a business failure (e.g., not authorized).
        dispatch({
          type: "BUSINESS_ERROR",
          message: result.message,
          failedStep: result.failedStep,
        });
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;

      const message =
        err instanceof ApiError
          ? (err.detail ?? err.message)
          : "An unexpected error occurred";

      dispatch({ type: "NETWORK_ERROR", message });
    }
  }, []);

  const reset = useCallback(() => dispatch({ type: "RESET" }), []);

  return { state, run, reset } as const;
}
