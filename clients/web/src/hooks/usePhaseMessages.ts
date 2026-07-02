import { useRef, useState, useEffect } from "react";
import { useAssistantMsg } from "@/contexts/AssistantMsgContext";
import { PHASE } from "@/types/ui";
import type { PipelinePhase } from "@/types/ui";

const MAX_MESSAGES_PER_PHASE = 3;

type PhaseMessageMap = Record<PipelinePhase, string[]>;

function emptyMap(): PhaseMessageMap {
  return {
    [PHASE.INIT]: [],
    [PHASE.RUNNING]: [],
    [PHASE.REPORT]: [],
    [PHASE.COMPLETE]: [],
    [PHASE.FINALIZING]: [],
  };
}

export function usePhaseMessages() {
  const { assistantMsgState } = useAssistantMsg();
  const mapRef = useRef<PhaseMessageMap>(emptyMap());
  const [, setTick] = useState(0);

  const { pipelineStep, isApplyMode } = assistantMsgState;
  const currentMessage = assistantMsgState.msg;

  useEffect(() => {
    if (!currentMessage) return;

    const bucket = mapRef.current[pipelineStep];
    if (bucket[bucket.length - 1] === currentMessage) return;

    bucket.push(currentMessage);
    if (bucket.length > MAX_MESSAGES_PER_PHASE) bucket.shift();

    setTick((t) => t + 1);
  }, [currentMessage, pipelineStep]);

  const last = (arr: string[]) => arr[arr.length - 1] ?? null;

  const latestByPhase: Record<PipelinePhase, string | null> = {
    [PHASE.INIT]: last(mapRef.current[PHASE.INIT]),
    [PHASE.RUNNING]: last(mapRef.current[PHASE.RUNNING]),
    [PHASE.REPORT]: last(mapRef.current[PHASE.REPORT]),
    [PHASE.COMPLETE]: last(mapRef.current[PHASE.COMPLETE]),
    [PHASE.FINALIZING]: last(mapRef.current[PHASE.FINALIZING]),
  };

  return {
    messagesByPhase: mapRef.current,
    latestByPhase,
    currentPhase: pipelineStep,
    isApplyMode,
  } as const;
}
