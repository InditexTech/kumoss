// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * HOOK: useTerraformActions
 *
 * Triggers a mode-based IaC endpoint, subscribes to SSE events,
 * updates pipeline progress via AssistantMsgContext, and resolves the
 * finished round into a SessionOutcome for the completion callback.
 */

import { useReducer, useRef, useCallback, useEffect } from "react";
import {
  runTerraformActionWorkflow,
  type TerraformActionParams,
} from "@/services/workflows/terraform_action";
import {
  subscribeToSession,
  checkSessionStatus,
  type SseConnection,
} from "@/services/core/events";
import {
  resolveSessionOutcome,
  waitForNewRound,
  type SessionOutcome,
} from "@/services/workflows/session_outcome";
import { getSessionDetail } from "@/services/core/sessions";
import { useAssistantMsg } from "@/contexts/AssistantMsgContext";
import { PHASE, EVENT_STATUS } from "@/types/ui";
import { ApiError } from "@/services/api";
import type { SessionEventData } from "@/types/api";
import { useBrowserNotification } from "@/hooks/useBrowserNotification";
import { STRINGS } from "@/constants/strings";

const SSE_INACTIVITY_TIMEOUT_MS = 90_000;

// ─── State machine ─────────────────────────────────────────────

type State =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "streaming"; sessionId: string }
  | { status: "success"; sessionId: string }
  | { status: "error"; message: string };

type Action =
  | { type: "START" }
  | { type: "STREAMING"; sessionId: string }
  | { type: "SUCCESS"; sessionId: string }
  | { type: "ERROR"; message: string }
  | { type: "RESET" };

function reducer(_state: State, action: Action): State {
  switch (action.type) {
    case "START":
      return { status: "loading" };
    case "STREAMING":
      return { status: "streaming", sessionId: action.sessionId };
    case "SUCCESS":
      return { status: "success", sessionId: action.sessionId };
    case "ERROR":
      return { status: "error", message: action.message };
    case "RESET":
      return { status: "idle" };
  }
}

function mapStatusToPhase(statusMsg: string) {
  switch (statusMsg) {
    case "STARTED":
    case "FILTERING":
      return PHASE.INIT;
    case "GENERATING":
    case "RECONCILING":
    case "VALIDATING":
    case "APPLY":
      return PHASE.RUNNING;
    case "REPORT":
      return PHASE.REPORT;
    case "COMPLETED":
    case "UNCOMPLETED":
      return PHASE.COMPLETE;
    default:
      return null;
  }
}

// ─── The hook ──────────────────────────────────────────────────

export function useTerraformActions() {
  const [state, dispatch] = useReducer(reducer, { status: "idle" });
  const eventSourceRef = useRef<SseConnection | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const inactivityTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { setAssistantMsgState } = useAssistantMsg();
  const { notifyIfHidden } = useBrowserNotification();

  const clearInactivityTimer = useCallback(() => {
    if (inactivityTimerRef.current !== null) {
      clearTimeout(inactivityTimerRef.current);
      inactivityTimerRef.current = null;
    }
  }, []);

  const resetInactivityTimer = useCallback(
    (es: SseConnection) => {
      clearInactivityTimer();
      inactivityTimerRef.current = setTimeout(() => {
        es.close();
        eventSourceRef.current = null;
        dispatch({
          type: "ERROR",
          message: "Connection timed out — no response from server",
        });
      }, SSE_INACTIVITY_TIMEOUT_MS);
    },
    [clearInactivityTimer],
  );

  useEffect(() => {
    return () => {
      eventSourceRef.current?.close();
      abortRef.current?.abort();
      clearInactivityTimer();
    };
  }, [clearInactivityTimer]);

  const run = useCallback(
    async (
      params: TerraformActionParams,
      onOutcome?: (outcome: SessionOutcome) => void,
    ) => {
      eventSourceRef.current?.close();
      abortRef.current?.abort();
      clearInactivityTimer();
      abortRef.current = new AbortController();
      const signal = abortRef.current.signal;

      dispatch({ type: "START" });

      setAssistantMsgState((prev) => ({
        ...prev,
        pipelineStep: PHASE.INIT,
        isApplyMode: params.mode === "import",
      }));

      const settleOutcome = (outcome: SessionOutcome, sessionId: string) => {
        clearInactivityTimer();

        if (outcome.kind === "failed") {
          dispatch({ type: "ERROR", message: outcome.message });
          setAssistantMsgState((prev) => ({
            ...prev,
            pipelineStep: PHASE.COMPLETE,
            sseStatus: EVENT_STATUS.FAILED,
            msg: outcome.message,
          }));
          notifyIfHidden("Pipeline failed", { body: outcome.message });
          onOutcome?.(outcome);
          return;
        }

        dispatch({ type: "SUCCESS", sessionId });
        setAssistantMsgState((prev) => ({
          ...prev,
          pipelineStep: PHASE.COMPLETE,
        }));

        if (outcome.kind === "rejected") {
          notifyIfHidden("Request rejected", { body: outcome.rationale });
        } else {
          notifyIfHidden("Pipeline completed", {
            body: "Your infrastructure changes are ready for review.",
          });
          if (outcome.detail.is_blocked) {
            notifyIfHidden("Session blocked", {
              body: "The proposed changes need a specialist review before they can be applied.",
              tag: "nebula-session-blocked",
            });
          }
        }

        onOutcome?.(outcome);
      };

      try {
        // Iteration/apply calls write no status synchronously — capture how
        // many rounds exist now so the new one can be told from the old.
        const baselineRounds = params.sessionId
          ? (await getSessionDetail(params.sessionId)).rounds.length
          : 0;
        if (signal.aborted) return;

        const { sessionId } = await runTerraformActionWorkflow(params, signal);
        if (signal.aborted) return;

        dispatch({ type: "STREAMING", sessionId });

        if (params.sessionId) {
          setAssistantMsgState((prev) => ({
            ...prev,
            pipelineStep: PHASE.INIT,
            sseStatus: "STARTED",
            msg: STRINGS.planning.preparingWorkspace,
          }));
          await waitForNewRound(sessionId, baselineRounds, signal);
          if (signal.aborted) return;
        }

        const createMessageHandler = (es: SseConnection) => {
          const finishRound = () => {
            es.close();
            eventSourceRef.current = null;
            clearInactivityTimer();

            resolveSessionOutcome(sessionId)
              .then((outcome) => settleOutcome(outcome, sessionId))
              .catch(() =>
                settleOutcome(
                  {
                    kind: "failed",
                    detail: null,
                    message: STRINGS.planning.resultsLoadError,
                  },
                  sessionId,
                ),
              );
          };

          return (event: { data: string }) => {
            resetInactivityTimer(es);
            try {
              const data: SessionEventData = JSON.parse(event.data);
              const phase = mapStatusToPhase(data.status_msg);

              if (phase) {
                setAssistantMsgState((prev) => ({
                  ...prev,
                  pipelineStep: phase,
                  sseStatus: data.status_msg,
                  msg: data.detail.message || prev.msg,
                }));
              }

              if (
                data.status_msg === EVENT_STATUS.COMPLETED ||
                data.status_msg === EVENT_STATUS.UNCOMPLETED
              ) {
                finishRound();
              }
              if (data.status_msg === EVENT_STATUS.FAILED) {
                es.close();
                eventSourceRef.current = null;
                clearInactivityTimer();
                settleOutcome(
                  {
                    kind: "failed",
                    detail: null,
                    message: data.detail.message || "Process failed",
                  },
                  sessionId,
                );
              }
            } catch (err) {
              console.error("SSE parse error:", err);
            }
          };
        };

        const es = subscribeToSession(sessionId);
        eventSourceRef.current = es;
        resetInactivityTimer(es);
        es.onmessage = createMessageHandler(es);

        es.onerror = () => {
          es.close();
          eventSourceRef.current = null;
          clearInactivityTimer();

          checkSessionStatus(sessionId)
            .then(async (result) => {
              if (
                result.status === "completed" ||
                result.status === "uncompleted" ||
                result.status === "failed"
              ) {
                try {
                  const outcome = await resolveSessionOutcome(sessionId);
                  settleOutcome(outcome, sessionId);
                } catch {
                  settleOutcome(
                    {
                      kind: "failed",
                      detail: null,
                      message:
                        result.status === "failed"
                          ? "Process failed"
                          : STRINGS.planning.resultsLoadError,
                    },
                    sessionId,
                  );
                }
                return;
              }

              if (result.status === "in_progress") {
                const newEs = subscribeToSession(sessionId);
                eventSourceRef.current = newEs;
                resetInactivityTimer(newEs);
                newEs.onmessage = createMessageHandler(newEs);
                newEs.onerror = () => {
                  newEs.close();
                  eventSourceRef.current = null;
                  clearInactivityTimer();
                  dispatch({
                    type: "ERROR",
                    message: "Connection to server lost",
                  });
                };
                return;
              }

              dispatch({
                type: "ERROR",
                message: "Connection to server lost",
              });
            })
            .catch(() => {
              dispatch({
                type: "ERROR",
                message: "Connection to server lost",
              });
            });
        };
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;

        const message =
          err instanceof ApiError
            ? (err.detail ?? err.message)
            : err instanceof Error && err.message
              ? err.message
              : "An unexpected error occurred";

        dispatch({ type: "ERROR", message });
      }
    },
    [
      setAssistantMsgState,
      notifyIfHidden,
      clearInactivityTimer,
      resetInactivityTimer,
    ],
  );

  const reset = useCallback(() => {
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    clearInactivityTimer();
    dispatch({ type: "RESET" });
  }, [clearInactivityTimer]);

  return { state, run, reset } as const;
}
