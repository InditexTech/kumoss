/**
 * HOOK: useTerraformActions
 *
 * Triggers a mode-based IaC endpoint, subscribes to SSE events,
 * updates pipeline progress via AssistantMsgContext, and drives
 * screen transitions on completion/failure.
 */

import { useReducer, useRef, useCallback, useEffect } from "react";
import {
  runTerraformActionWorkflow,
  type TerraformActionParams,
} from "@/services/workflows/terraform_action";
import {
  subscribeToSession,
  getSessionData,
  type SseConnection,
} from "@/services/core/events";
import { useAssistantMsg } from "@/contexts/AssistantMsgContext";
import { PHASE, EVENT_STATUS } from "@/types/ui";
import { ApiError } from "@/services/api";
import type { SessionPayloadResponse } from "@/types/api";
import { useBrowserNotification } from "@/hooks/useBrowserNotification";

const SSE_INACTIVITY_TIMEOUT_MS = 90_000;

// ─── SSE event shape ──────────────────────────────────────────

interface SseEventData {
  status_msg: string;
  detail: {
    validation_id: string | null;
    message: string;
  };
}

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
    case "VALIDATING":
      return PHASE.RUNNING;
    case "REPORT":
      return PHASE.REPORT;
    case "COMPLETED":
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
      onCompleted?: (payload: SessionPayloadResponse) => void,
    ) => {
      eventSourceRef.current?.close();
      abortRef.current?.abort();
      clearInactivityTimer();
      abortRef.current = new AbortController();

      dispatch({ type: "START" });

      setAssistantMsgState((prev) => ({
        ...prev,
        pipelineStep: PHASE.INIT,
        isApplyMode: params.mode === "import",
      }));

      try {
        const { sessionId } = await runTerraformActionWorkflow(
          params,
          abortRef.current.signal,
        );

        dispatch({ type: "STREAMING", sessionId });

        const es = subscribeToSession(sessionId);
        eventSourceRef.current = es;
        resetInactivityTimer(es);

        es.onmessage = (event) => {
          resetInactivityTimer(es);
          try {
            const data: SseEventData = JSON.parse(event.data);
            const phase = mapStatusToPhase(data.status_msg);

            if (phase) {
              setAssistantMsgState((prev) => ({
                ...prev,
                pipelineStep: phase,
                sseStatus: data.status_msg,
                msg: data.detail.message || prev.msg,
              }));
            }

            if (data.status_msg === EVENT_STATUS.COMPLETED) {
              es.close();
              eventSourceRef.current = null;
              clearInactivityTimer();
              dispatch({ type: "SUCCESS", sessionId });
              setAssistantMsgState((prev) => ({
                ...prev,
                pipelineStep: PHASE.COMPLETE,
              }));
              notifyIfHidden("Pipeline completed", {
                body: "Your infrastructure changes are ready for review.",
              });

              getSessionData(sessionId)
                .then((payload) => {
                  if (
                    payload.terraform_report?.potential_impact?.banner
                      ?.level === "high"
                  ) {
                    notifyIfHidden("High impact changes detected", {
                      body:
                        payload.terraform_report.potential_impact.banner
                          .description ||
                        "Review the potential impact before proceeding.",
                      tag: "nebula-high-impact",
                    });
                  }
                  onCompleted?.(payload);
                })
                .catch((err) =>
                  console.error("Failed to fetch session data:", err),
                );
            }

            if (data.status_msg === EVENT_STATUS.FAILED) {
              es.close();
              eventSourceRef.current = null;
              clearInactivityTimer();

              const failMsg = data.detail.message || "Process failed";

              dispatch({ type: "ERROR", message: failMsg });
              setAssistantMsgState((prev) => ({
                ...prev,
                pipelineStep: PHASE.COMPLETE,
                sseStatus: EVENT_STATUS.FAILED,
                msg: failMsg,
              }));
              notifyIfHidden("Pipeline failed", { body: failMsg });
            }
          } catch (err) {
            console.error("SSE parse error:", err);
          }
        };

        es.onerror = () => {
          es.close();
          eventSourceRef.current = null;
          clearInactivityTimer();
          dispatch({
            type: "ERROR",
            message: "Connection to server lost",
          });
        };
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;

        const message =
          err instanceof ApiError
            ? (err.detail ?? err.message)
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
