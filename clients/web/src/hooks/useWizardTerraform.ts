import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useSession } from "@/contexts/SessionContext";
import { invalidateSessionsCache } from "@/services/core/sessionsCache";
import type { SessionPayloadResponse } from "@/types/api";

export function useWizardTerraform() {
  const { updateSession } = useSession();
  const navigate = useNavigate();

  const syncSession = useCallback(
    (payload: SessionPayloadResponse) => {
      invalidateSessionsCache();
      updateSession({
        session_id: payload.id,
        full_history: payload.full_history,
        terraform_report: payload.terraform_report ?? undefined,
        branchName: payload.branch_name,
        terraform_targets: payload.terraform_targets ?? undefined,
        cloud: payload.cloud,
        project: payload.project,
        pipeline_url: payload.pipeline_url ?? undefined,
        apply_allowed: payload.apply_allowed,
      });
    },
    [updateSession],
  );

  const handleCompleted = useCallback(
    (payload: SessionPayloadResponse) => {
      syncSession(payload);
      updateSession({ code: payload.response });
      navigate(`/home/results/${payload.id}`, { replace: true });
    },
    [syncSession, updateSession, navigate],
  );

  const handleApplyCompleted = useCallback(
    (payload: SessionPayloadResponse) => {
      syncSession(payload);
      updateSession({
        applyResults: {
          sessionId: payload.id,
          status: payload.terraform_report?.status ?? "Unknown",
          message: payload.response,
          errorMessage: "",
          timestamp: new Date().toISOString(),
          applyReport: payload.terraform_report,
          resultsUrl: payload.pipeline_url ?? undefined,
        },
      });
      navigate(`/home/apply-results/${payload.id}`, { replace: true });
    },
    [syncSession, updateSession, navigate],
  );

  return { handleCompleted, handleApplyCompleted } as const;
}
