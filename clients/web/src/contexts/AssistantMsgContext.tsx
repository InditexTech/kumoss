import React, { createContext, useContext, useState, useMemo } from "react";
import { PHASE } from "@/types/ui";
import type { AssistantMsgState, StateSetter } from "@/types/ui";

interface AssistantMsgContextValue {
  assistantMsgState: AssistantMsgState;
  setAssistantMsgState: StateSetter<AssistantMsgState>;
}

const AssistantMsgContext = createContext<AssistantMsgContextValue | undefined>(undefined);

export { AssistantMsgContext };

export const useAssistantMsg = () => {
  const ctx = useContext(AssistantMsgContext);
  if (!ctx) throw new Error("useAssistantMsg must be used within AssistantMsgProvider");
  return ctx;
};

export const AssistantMsgProvider = ({ children }: { children: React.ReactNode }) => {
  const [assistantMsgState, setAssistantMsgState] = useState<AssistantMsgState>({
    msg: "Coming right up! Give me a second to check your infrastructure",
    pipelineStep: PHASE.INIT,
    sseStatus: "",
    showPR: false,
    showTFApply: false,
    showPipeline: false,
    isApplyMode: false,
  });

  const value = useMemo(
    () => ({ assistantMsgState, setAssistantMsgState }),
    [assistantMsgState]
  );

  return (
    <AssistantMsgContext.Provider value={value}>
      {children}
    </AssistantMsgContext.Provider>
  );
};
