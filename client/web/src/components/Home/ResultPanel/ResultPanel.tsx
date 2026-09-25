// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useMemo, useEffect, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import Fade from "@mui/material/Fade";
import Typography from "@mui/material/Typography";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import { useSession } from "@/contexts/SessionContext";
import { CodeBlock, StatusBadge } from "@/components/ui";
import { STRINGS } from "@/constants/strings";
import { processTerraformPlan } from "@/utils/terraformUtils";
import {
  extractCodeFiles,
  hasStructuredCosts,
  reportStatusVariant,
} from "./resultPanelUtils";
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
import {
  DriftChangesList,
  DriftLeftovers,
  DriftResourceDetail,
} from "./DriftReport/DriftReport";
import {
  ImportedResourcesList,
  ImportExclusions,
  ImportStateAlignment,
  ImportedResourceDetail,
} from "./ImportReport/ImportReport";
import type { ImportFilterId } from "./ImportReport/ImportReport";
import { ApplyRecommendations } from "./ApplyReport/ApplyReport";
import styles from "./ResultPanel.module.css";

const TAB_FADE_MS = 300;
const VALID_DETAILS: DetailView[] = ["impact", "costs", "change"];
const LABELS_TARGETS = STRINGS.sessions.artifactTargets;

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
  const [importFilter, setImportFilter] = useState<ImportFilterId>("all");
  const [selectedFile, setSelectedFile] = useState("");
  const [targetsOpen, setTargetsOpen] = useState(true);

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
  // Drift reports carry `remediated_resources` and a prose `summary`
  // instead of the plan report's `detailed_changes`.
  const driftResources = report?.remediated_resources;
  // Import reports carry `imported_resources` (one per attempted import).
  const importedResources = report?.imported_resources;
  const reportStatus =
    driftResources || importedResources
      ? reportStatusVariant(report?.status)
      : null;
  const summaryText =
    report?.execution_summary ??
    (typeof report?.summary === "string" ? report.summary : undefined);

  const selectedChange = useMemo(() => {
    if (activeDetail !== "change" || !resourceParam || !report?.detailed_changes) return null;
    return report.detailed_changes.find((c) => c.name === resourceParam) ?? null;
  }, [activeDetail, resourceParam, report?.detailed_changes]);

  const selectedDriftResource = useMemo(() => {
    if (activeDetail !== "change" || !resourceParam || !driftResources) return null;
    return driftResources.find((r) => r.resource_address === resourceParam) ?? null;
  }, [activeDetail, resourceParam, driftResources]);

  const selectedImportedResource = useMemo(() => {
    if (activeDetail !== "change" || !resourceParam || !importedResources) return null;
    return importedResources.find((r) => r.resource_address === resourceParam) ?? null;
  }, [activeDetail, resourceParam, importedResources]);
  const code = session.code ?? "";
  const planCode = useMemo(
    () => processTerraformPlan(code)["Terraform_Plan"] ?? "",
    [code],
  );
  const codeFiles = useMemo(
    () => extractCodeFiles(code),
    [code],
  );
  // Addresses the displayed plan was narrowed to. Session state rather than
  // report data: they come off the plan artifact the resolver selected, so a
  // report has no way to carry them (see `session_outcome.fetchPlanContent`).
  const planTargets = session.planTargets ?? [];

  return (
    <div className={styles.panel}>
      <div className={styles.tabBar}>
        <Typography
          variant="h1"
          component="button"
          className={`${styles.tab} ${activeTab === "plan" ? styles.tabActive : ""}`}
          onClick={() => handleTabChange("plan")}
        >
          Plan
        </Typography>
        <Typography
          variant="h1"
          component="button"
          className={`${styles.tab} ${activeTab === "code" ? styles.tabActive : ""}`}
          onClick={() => handleTabChange("code")}
        >
          Code
        </Typography>
        <Typography
          variant="h1"
          component="button"
          className={`${styles.tab} ${activeTab === "report" ? styles.tabActive : ""}`}
          onClick={() => handleTabChange("report")}
        >
          Report
        </Typography>
      </div>

      <Fade in key={activeTab} timeout={TAB_FADE_MS}>
        <div className={styles.tabContent}>
          {activeTab === "plan" && (
            <div className={styles.planView}>
              {planCode ? (
                <>
                  {planTargets.length > 0 && (
                    <div className={styles.targets}>
                      <button
                        type="button"
                        className={styles.targetsToggle}
                        onClick={() => setTargetsOpen((open) => !open)}
                        aria-expanded={targetsOpen}
                      >
                        {targetsOpen ? (
                          <ExpandLessIcon
                            className={styles.targetsToggleIcon}
                          />
                        ) : (
                          <ExpandMoreIcon
                            className={styles.targetsToggleIcon}
                          />
                        )}
                        {`${LABELS_TARGETS} (${planTargets.length})`}
                      </button>
                      {targetsOpen && (
                        <ul className={styles.targetsList}>
                          {planTargets.map((target) => (
                            <li key={target} className={styles.targetsItem}>
                              {target}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                  {/* The editor takes `height="100%"`, so it needs a box that
                      owns the space the targets block leaves — unlike the
                      session panel's copy, which reserves it with fixed
                      `calc()` heights. */}
                  <div className={styles.planEditor}>
                    <CodeBlock
                      code={planCode}
                      language="hcl"
                      showLineNumbers
                      height="100%"
                    />
                  </div>
                </>
              ) : (
                <Typography variant="bodyText" className={styles.emptyState}>
                  No terraform plan available to display.
                </Typography>
              )}
            </div>
          )}

          {activeTab === "code" && (
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

          {activeTab === "report" && report && (
            <>
              {summaryText && (
                <div className={styles.executionSummary}>
                  <Typography variant="label" className={styles.executionSummaryLabel}>
                    {driftResources
                      ? "Drift Summary"
                      : importedResources
                        ? "Import Summary"
                        : "Execution Summary"}
                    {reportStatus && (
                      <StatusBadge
                        variant={reportStatus}
                        className={styles.summaryStatusBadge}
                      />
                    )}
                  </Typography>
                  <Typography variant="bodyText" className={styles.executionSummaryText}>
                    {summaryText}
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
              {hasStructuredCosts(report.estimated_costs) && (
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
              {importedResources ? (
                <>
                  <ImportedResourcesList
                    resources={importedResources}
                    activeFilter={importFilter}
                    setActiveFilter={setImportFilter}
                    onSelect={(resource) => {
                      setActiveDetail("change", resource.resource_address);
                    }}
                  />
                  <ImportExclusions excluded={report.excluded_resources} />
                  <ImportStateAlignment text={report.state_alignment} />
                  <ApplyRecommendations
                    recommendations={report.recommendations ?? []}
                  />
                </>
              ) : driftResources ? (
                <>
                  <DriftChangesList
                    resources={driftResources}
                    onSelect={(resource) => {
                      setActiveDetail("change", resource.resource_address);
                    }}
                  />
                  <DriftLeftovers
                    unreconciled={report.unreconciled_drift}
                    exceptions={report.whitelisted_exceptions}
                  />
                </>
              ) : (
                <ChangesTable
                  changes={report.detailed_changes ?? []}
                  activeFilter={activeFilter}
                  setActiveFilter={setActiveFilter}
                  onSelectChange={(change) => {
                    setActiveDetail("change", change.name);
                  }}
                />
              )}

              {activeDetail === "impact" && report.potential_impact && (
                <ImpactDetail
                  impact={report.potential_impact}
                  onClose={() => setActiveDetail(null)}
                />
              )}
              {activeDetail === "costs" && hasStructuredCosts(report.estimated_costs) && (
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
              {activeDetail === "change" && selectedDriftResource && (
                <DriftResourceDetail
                  resource={selectedDriftResource}
                  onClose={() => setActiveDetail(null)}
                />
              )}
              {activeDetail === "change" && selectedImportedResource && (
                <ImportedResourceDetail
                  resource={selectedImportedResource}
                  onClose={() => setActiveDetail(null)}
                />
              )}
            </>
          )}

          {activeTab === "report" && !report && (
            <Typography variant="bodyText" className={styles.emptyState}>No report data available.</Typography>
          )}
        </div>
      </Fade>
    </div>
  );
}
