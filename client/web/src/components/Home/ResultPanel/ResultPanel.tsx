// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useMemo, useEffect, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import Fade from "@mui/material/Fade";
import Typography from "@mui/material/Typography";
import { useSession } from "@/contexts/SessionContext";
import { useMode } from "@/contexts/ModeContext";
import { CodeBlock } from "@/components/ui";
import { processTerraformPlan } from "@/utils/terraformUtils";
import { extractCodeFiles } from "./resultPanelUtils";
import type { DetailView, FilterId } from "./resultPanelUtils";
import {
  PotentialImpactCard,
  ImpactDetail,
} from "./PotentialImpact/PotentialImpact";
import {
  EstimatedCostsCard,
  CostsDetail,
} from "./EstimatedCosts/EstimatedCosts";
import ChangesTable from "./ChangesTable/ChangesTable";
import ChangeDetail from "./ChangeDetail/ChangeDetail";
import styles from "./ResultPanel.module.css";

const TAB_FADE_MS = 300;
const VALID_DETAILS: DetailView[] = ["impact", "costs", "change"];

export type TabId = "plan" | "code" | "report";

interface ResultPanelProps {
  tab?: TabId;
  onTabChange?: (tab: TabId) => void;
}

export default function ResultPanel({
  tab,
  onTabChange,
}: ResultPanelProps = {}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [internalTab, setInternalTab] = useState<TabId>("report");
  const [activeFilter, setActiveFilter] = useState<FilterId>("all");
  const [selectedFile, setSelectedFile] = useState("");

  const rawDetail = searchParams.get("detail") as DetailView;
  const activeDetail: DetailView =
    rawDetail && VALID_DETAILS.includes(rawDetail) ? rawDetail : null;

  const resourceParam = searchParams.get("resource");

  const setActiveDetail = useCallback(
    (detail: DetailView, resourceName?: string) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (detail) {
          next.set("detail", detail);
        } else {
          next.delete("detail");
        }
        if (resourceName) {
          next.set("resource", resourceName);
        } else {
          next.delete("resource");
        }
        return next;
      });
    },
    [setSearchParams],
  );

  const activeTab = tab ?? internalTab;

  const { session } = useSession();
  const { isImportMode } = useMode();

  const handleTabChange = (t: TabId) => {
    if (onTabChange) {
      onTabChange(t);
    } else {
      setInternalTab(t);
      setActiveDetail(null);
    }
  };

  useEffect(() => {
    if (!activeDetail) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setActiveDetail(null);
    };
    const onClick = (e: MouseEvent) => {
      if (!(e.target as HTMLElement).closest("[data-detail-content]")) {
        setActiveDetail(null);
      }
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [activeDetail, setActiveDetail]);

  const report = session.terraform_report ?? null;

  const selectedChange = useMemo(() => {
    if (activeDetail !== "change" || !resourceParam || !report?.detailed_changes) return null;
    return report.detailed_changes.find((c) => c.name === resourceParam) ?? null;
  }, [activeDetail, resourceParam, report?.detailed_changes]);
  const code = session.code ?? "";
  const planCode = useMemo(
    () => processTerraformPlan(code)["Terraform_Plan"] ?? "",
    [code],
  );
  const codeFiles = useMemo(
    () => extractCodeFiles(code),
    [code],
  );

  const effectiveTab =
    isImportMode && activeTab === "code" ? "plan" : activeTab;

  return (
    <div className={styles.panel}>
      <div className={styles.tabBar}>
        <Typography
          variant="h1"
          component="button"
          className={`${styles.tab} ${effectiveTab === "plan" ? styles.tabActive : ""}`}
          onClick={() => handleTabChange("plan")}
        >
          Plan
        </Typography>
        {!isImportMode && (
          <Typography
            variant="h1"
            component="button"
            className={`${styles.tab} ${effectiveTab === "code" ? styles.tabActive : ""}`}
            onClick={() => handleTabChange("code")}
          >
            Code
          </Typography>
        )}
        <Typography
          variant="h1"
          component="button"
          className={`${styles.tab} ${effectiveTab === "report" ? styles.tabActive : ""}`}
          onClick={() => handleTabChange("report")}
        >
          Report
        </Typography>
      </div>

      <Fade in key={effectiveTab} timeout={TAB_FADE_MS}>
        <div className={styles.tabContent}>
          {effectiveTab === "plan" && (
            <div className={styles.planView}>
              {planCode ? (
                <CodeBlock
                  code={planCode}
                  language="hcl"
                  showLineNumbers
                  height="100%"
                />
              ) : (
                <Typography variant="bodyText" className={styles.emptyState}>
                  No terraform plan available to display.
                </Typography>
              )}
            </div>
          )}

          {effectiveTab === "code" && (
            <div className={styles.codeView}>
              {Object.keys(codeFiles).length > 0 ? (
                <CodeBlock
                  files={codeFiles}
                  activeFile={selectedFile || Object.keys(codeFiles)[0]}
                  onFileChange={setSelectedFile}
                  showLineNumbers
                  height="100%"
                />
              ) : (
                <Typography variant="bodyText" className={styles.emptyState}>
                  No code available to display.
                </Typography>
              )}
            </div>
          )}

          {effectiveTab === "report" && report && (
            <>
              {report.execution_summary && (
                <div className={styles.executionSummary}>
                  <Typography variant="label" className={styles.executionSummaryLabel}>
                    Execution Summary
                  </Typography>
                  <Typography variant="bodyText" className={styles.executionSummaryText}>
                    {report.execution_summary}
                  </Typography>
                </div>
              )}
              {report.potential_impact && (
                <div
                  className={styles.reportCard}
                  onClick={() => setActiveDetail("impact")}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) =>
                    e.key === "Enter" && setActiveDetail("impact")
                  }
                >
                  <PotentialImpactCard impact={report.potential_impact} />
                </div>
              )}
              {report.estimated_costs && (
                <div
                  className={styles.reportCard}
                  onClick={() => setActiveDetail("costs")}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) =>
                    e.key === "Enter" && setActiveDetail("costs")
                  }
                >
                  <EstimatedCostsCard costs={report.estimated_costs} />
                </div>
              )}
              <ChangesTable
                changes={report.detailed_changes ?? []}
                activeFilter={activeFilter}
                setActiveFilter={setActiveFilter}
                onSelectChange={(change) => {
                  setActiveDetail("change", change.name);
                }}
              />

              {activeDetail === "impact" && report.potential_impact && (
                <ImpactDetail
                  impact={report.potential_impact}
                  onClose={() => setActiveDetail(null)}
                />
              )}
              {activeDetail === "costs" && report.estimated_costs && (
                <CostsDetail
                  costs={report.estimated_costs}
                  onClose={() => setActiveDetail(null)}
                />
              )}
              {activeDetail === "change" && selectedChange && (
                <ChangeDetail
                  change={selectedChange}
                  onClose={() => setActiveDetail(null)}
                />
              )}
            </>
          )}

          {effectiveTab === "report" && !report && (
            <Typography variant="bodyText" className={styles.emptyState}>No report data available.</Typography>
          )}
        </div>
      </Fade>
    </div>
  );
}
