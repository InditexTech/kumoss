// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useMemo, useEffect, useCallback } from "react";
import Typography from "@mui/material/Typography";
import { useSearchParams } from "react-router-dom";
import { fetchArtifactContent } from "@/services/core/sessions";
import { useMode } from "@/contexts/ModeContext";
import type {
  ArtifactRef,
  CodeChangeRef,
  OperationType,
  ReportRef,
  ReportType,
  RoundDetail,
} from "@/types/api";
import type { TerraformReport } from "@/types";
import {
  ChangesTable,
  ChangeDetail,
  PotentialImpactCard,
  ImpactDetail,
  EstimatedCostsCard,
  CostsDetail,
  DriftChangesList,
  DriftLeftovers,
  DriftResourceDetail,
  ApplyChangesList,
  ApplyResourceDetail,
  ApplyRecommendations,
  ImportedResourcesList,
  ImportExclusions,
  ImportStateAlignment,
  ImportedResourceDetail,
  hasStructuredCosts,
  reportStatusVariant,
} from "@/components/Home";
import type {
  FilterId,
  DetailView,
  ApplyFilterId,
  ImportFilterId,
} from "@/components/Home";
import { CodeBlock, StatusBadge } from "@/components/ui";
import { composeFileArtifacts } from "@/utils/diffUtils";
import styles from "./ArtifactContent.module.css";

export type ArtifactKind = "report" | "plan" | "change";

interface ArtifactContentProps {
  kind: ArtifactKind;
  artifact: ArtifactRef;
  round: RoundDetail;
  operation: OperationType;
}

// Apply, drift and import reports announce themselves; generate ones are
// just "Report".
const REPORT_LABELS: Partial<Record<ReportType, string>> = {
  apply: "Apply Report",
  drift: "Drift Report",
  import: "Import Report",
};

export function artifactLabel(kind: ArtifactKind, artifact: ArtifactRef): string {
  switch (kind) {
    case "report":
      return REPORT_LABELS[(artifact as ReportRef).type] ?? "Report";
    case "plan":
      return "Terraform Plan";
    case "change":
      return (artifact as CodeChangeRef).file_name;
  }
}

function getLanguage(kind: ArtifactKind, artifact: ArtifactRef): string {
  if (artifact.content_type?.includes("json")) return "json";
  if (kind === "plan") return "hcl";
  if (kind === "change" && (artifact as CodeChangeRef).file_name.endsWith(".tf"))
    return "hcl";
  return "plaintext";
}

export default function ArtifactContent({
  kind,
  artifact,
  round,
  operation,
}: Readonly<ArtifactContentProps>) {
  const [content, setContent] = useState<string | null>(null);
  const [files, setFiles] = useState<Record<string, string> | null>(null);
  const [loading, setLoading] = useState(true);
  const [applyFilter, setApplyFilter] = useState<ApplyFilterId>("all");
  const [importFilter, setImportFilter] = useState<ImportFilterId>("all");
  const { setMode } = useMode();

  const [searchParams, setSearchParams] = useSearchParams();

  const VALID_DETAILS: DetailView[] = ["impact", "costs", "change"];
  const VALID_FILTERS: FilterId[] = ["all", "create", "update", "delete", "recreate"];

  const rawDetail = searchParams.get("detail") as DetailView;
  const activeDetail: DetailView =
    rawDetail && VALID_DETAILS.includes(rawDetail) ? rawDetail : null;

  const resourceParam = searchParams.get("resource");

  const rawFilter = searchParams.get("filter") as FilterId;
  const activeFilter: FilterId =
    rawFilter && VALID_FILTERS.includes(rawFilter) ? rawFilter : "all";

  const activeFile = searchParams.get("file") || "";

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

  const setActiveFilter = useCallback(
    (filter: FilterId) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (filter && filter !== "all") {
          next.set("filter", filter);
        } else {
          next.delete("filter");
        }
        return next;
      });
    },
    [setSearchParams],
  );

  const setActiveFile = useCallback(
    (file: string) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        if (file) {
          next.set("file", file);
        } else {
          next.delete("file");
        }
        return next;
      });
    },
    [setSearchParams],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setContent(null);
    setFiles(null);

    (async () => {
      try {
        if (kind === "change") {
          const contents = await Promise.all(
            round.code_changes.map((c) => fetchArtifactContent(c.url)),
          );
          if (cancelled) return;
          // A round can carry several sequential-diff artifacts for the
          // same file — collapse each file's group into one cumulative
          // artifact instead of letting the last overwrite the rest.
          const grouped = new Map<string, string[]>();
          round.code_changes.forEach((c, i) => {
            const group = grouped.get(c.file_name);
            if (group) {
              group.push(contents[i]);
            } else {
              grouped.set(c.file_name, [contents[i]]);
            }
          });
          const record: Record<string, string> = {};
          for (const [fileName, group] of grouped) {
            record[fileName] = composeFileArtifacts(fileName, group);
          }
          setFiles(record);
        } else {
          const text = await fetchArtifactContent(artifact.url);
          if (cancelled) return;
          setContent(text);
        }
      } catch {
        // leave content/files null → error state
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [kind, artifact.url, round]);

  useEffect(() => {
    if (kind === "report") {
      setMode(
        operation === "drift"
          ? "drift"
          : operation === "import"
            ? "import"
            : "generate",
      );
    }
    return () => setMode("generate");
  }, [kind, operation, setMode]);

  const reportData: TerraformReport | null = useMemo(() => {
    if (kind !== "report" || !content) return null;
    try {
      return JSON.parse(content);
    } catch {
      return null;
    }
  }, [kind, content]);

  const selectedChange = useMemo(() => {
    if (activeDetail !== "change" || !resourceParam || !reportData?.detailed_changes) return null;
    return reportData.detailed_changes.find((c) => c.name === resourceParam) ?? null;
  }, [activeDetail, resourceParam, reportData?.detailed_changes]);

  // The report ref's `type` (the reports.type column, surfaced by the
  // session detail read model) decides which renderer handles it;
  // generate goes through the plan table.
  const reportType = kind === "report" ? (artifact as ReportRef).type : null;

  // Drift reports carry `remediated_resources` and a prose `summary`
  // instead of the plan report's `detailed_changes`.
  const driftResources = reportData?.remediated_resources;
  const selectedDriftResource = useMemo(() => {
    if (activeDetail !== "change" || !resourceParam || !driftResources) return null;
    return driftResources.find((r) => r.resource_address === resourceParam) ?? null;
  }, [activeDetail, resourceParam, driftResources]);

  // Apply reports carry `resource_changes` (what actually happened per
  // resource) plus `recommendations` and an overall `status`.
  const applyChanges = reportData?.resource_changes;
  const selectedApplyChange = useMemo(() => {
    if (activeDetail !== "change" || !resourceParam || !applyChanges) return null;
    return applyChanges.find((c) => c.resource_name === resourceParam) ?? null;
  }, [activeDetail, resourceParam, applyChanges]);

  // Import reports carry `imported_resources` (one per attempted import),
  // the `excluded_resources` the exception list withheld, and a
  // `state_alignment` note.
  const importedResources =
    reportType === "import" ? reportData?.imported_resources : undefined;
  const selectedImportedResource = useMemo(() => {
    if (activeDetail !== "change" || !resourceParam || !importedResources) return null;
    return importedResources.find((r) => r.resource_address === resourceParam) ?? null;
  }, [activeDetail, resourceParam, importedResources]);

  const fileNames = files ? Object.keys(files) : [];
  const clickedFileName =
    kind === "change" ? (artifact as CodeChangeRef).file_name : "";
  const effectiveActiveFile =
    activeFile || clickedFileName || (fileNames.length > 0 ? fileNames[0] : "");

  if (loading) {
    return <Typography variant="subtitle2" component="div" className={styles.loading}>Loading artifact...</Typography>;
  }

  if (kind === "change") {
    if (!files || fileNames.length === 0) {
      return <Typography variant="subtitle2" component="div" className={styles.loading}>Failed to load artifact</Typography>;
    }
    return (
      <CodeBlock
        files={files}
        activeFile={effectiveActiveFile}
        onFileChange={setActiveFile}
        showLineNumbers
        height="calc(100vh - 200px)"
      />
    );
  }

  if (content === null) {
    return <Typography variant="subtitle2" component="div" className={styles.loading}>Failed to load artifact</Typography>;
  }

  const summaryText =
    reportData?.execution_summary ??
    (typeof reportData?.summary === "string" ? reportData.summary : undefined);

  // Apply, drift and import reports badge the round's overall outcome
  // next to the summary label; generate ones carry no such status.
  const reportStatus =
    reportType === "apply" || reportType === "drift" || reportType === "import"
      ? reportStatusVariant(reportData?.status)
      : null;

  if (kind === "report" && reportData) {
    function renderChanges(report: TerraformReport) {
      switch (reportType) {
        case "apply":
          return (
            <>
              <ApplyChangesList
                changes={report.resource_changes ?? []}
                activeFilter={applyFilter}
                setActiveFilter={setApplyFilter}
                onSelect={(change) => {
                  setActiveDetail("change", change.resource_name);
                }}
              />
              <ApplyRecommendations
                recommendations={report.recommendations ?? []}
              />
            </>
          );
        case "drift":
          return (
            <>
              <DriftChangesList
                resources={report.remediated_resources ?? []}
                onSelect={(resource) => {
                  setActiveDetail("change", resource.resource_address);
                }}
              />
              <DriftLeftovers
                unreconciled={report.unreconciled_drift}
                exceptions={report.whitelisted_exceptions}
              />
            </>
          );
        case "import":
          return (
            <>
              <ImportedResourcesList
                resources={report.imported_resources ?? []}
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
          );
        default:
          return (
            <ChangesTable
              changes={report.detailed_changes ?? []}
              activeFilter={activeFilter}
              setActiveFilter={setActiveFilter}
              onSelectChange={(change) => {
                setActiveDetail("change", change.name);
              }}
            />
          );
      }
    }

    return (
      <div className={styles.reportContainer}>
        {summaryText && (
          <div className={styles.executionSummary}>
            <Typography variant="label" className={styles.executionSummaryLabel}>
              {reportType === "drift"
                ? "Drift Summary"
                : reportType === "import"
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
        {reportData.potential_impact && (
          <div
            className={styles.reportCard}
            onClick={() => setActiveDetail("impact")}
            role="button"
            tabIndex={0}
            onKeyDown={(e) =>
              e.key === "Enter" && setActiveDetail("impact")
            }
          >
            <PotentialImpactCard impact={reportData.potential_impact} />
          </div>
        )}
        {hasStructuredCosts(reportData.estimated_costs) && (
          <div
            className={styles.reportCard}
            onClick={() => setActiveDetail("costs")}
            role="button"
            tabIndex={0}
            onKeyDown={(e) =>
              e.key === "Enter" && setActiveDetail("costs")
            }
          >
            <EstimatedCostsCard costs={reportData.estimated_costs} />
          </div>
        )}
        {renderChanges(reportData)}

        {activeDetail === "impact" && reportData.potential_impact && (
          <ImpactDetail
            impact={reportData.potential_impact}
            onClose={() => setActiveDetail(null)}
          />
        )}
        {activeDetail === "costs" && hasStructuredCosts(reportData.estimated_costs) && (
          <CostsDetail
            costs={reportData.estimated_costs}
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
        {activeDetail === "change" && selectedApplyChange && (
          <ApplyResourceDetail
            change={selectedApplyChange}
            onClose={() => setActiveDetail(null)}
          />
        )}
      </div>
    );
  }

  return (
    <CodeBlock
      code={content}
      language={getLanguage(kind, artifact)}
      showLineNumbers
      height="calc(100vh - 200px)"
    />
  );
}
