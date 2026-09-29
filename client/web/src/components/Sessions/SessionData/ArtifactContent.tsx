// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useMemo, useEffect, useCallback, useRef } from "react";
import Typography from "@mui/material/Typography";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import { useSearchParams } from "react-router-dom";
import { fetchArtifact } from "@/services/core/sessions";
import { useMode } from "@/contexts/ModeContext";
import type {
  ArtifactRef,
  CodeChangeRef,
  OperationType,
  PlanType,
  ReportRef,
  ReportType,
  TerraformPlanRef,
} from "@/types/api";
import type { ComplianceReport, TerraformReport } from "@/types";
import { STRINGS } from "@/constants/strings";
import {
  ChangesTable,
  ChangeDetail,
  ComplianceRules,
  ComplianceSummaryCard,
  ComplianceViolations,
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
import styles from "./ArtifactContent.module.css";

export type ArtifactKind = "report" | "plan" | "change" | "compliance";

interface ArtifactContentProps {
  kind: ArtifactKind;
  artifact: ArtifactRef;
  operation: OperationType;
  /**
   * Reports the flavour that came back with the plan body. Opening a
   * plan answers the question the timeline was asking anyway, so the
   * answer goes back up rather than being re-fetched per row.
   */
  onPlanType?: (id: number, type: PlanType) => void;
}

const LABELS = STRINGS.sessions.artifactLabels;
const LABELS_TARGETS = STRINGS.sessions.artifactTargets;

/**
 * The editor takes a fixed height, so the targets block above it reserves
 * its own: one line for the toggle, plus the list's bounded height when
 * it is open. Constant either way — the list scrolls rather than growing
 * with the target count.
 */
const EDITOR_HEIGHT = "calc(100vh - 200px)";
const EDITOR_HEIGHT_TARGETS_CLOSED = "calc(100vh - 248px)";
const EDITOR_HEIGHT_TARGETS_OPEN = "calc(100vh - 376px)";

const REPORT_LABELS: Partial<Record<ReportType, string>> = {
  apply: LABELS.applyReport,
  drift: LABELS.driftReport,
  import: LABELS.importReport,
};

export function artifactLabel(
  kind: ArtifactKind,
  artifact: ArtifactRef,
  planType?: PlanType | null,
): string {
  switch (kind) {
    case "report":
      return REPORT_LABELS[(artifact as ReportRef).type] ?? LABELS.report;
    case "compliance":
      return LABELS.complianceCheck;
    case "plan":
      // A drift round stores both the diff and the plan it produced, and
      // only the object's `type` metadata tells them apart — so the caller
      // resolves it (`usePlanTypes`) and passes it in. Unresolved falls to
      // the neutral label rather than announcing a plan as drift.
      return planType === "drift"
        ? LABELS.driftOperation
        : LABELS.terraformPlan;
    case "change":
      // A file name, not copy: nothing to translate.
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

/**
 * Past this, indenting costs more than the horizontal scrolling it saves:
 * the re-serialized copy plus Monaco's tokenization of it is the expense,
 * not the parse.
 */
const MAX_PRETTY_JSON_BYTES = 512 * 1024;

/**
 * Re-emits a JSON body indented, or null if the body isn't JSON.
 *
 * Plans are uploaded as `text/plain` whatever the producer actually wrote,
 * so `content_type` can't be asked and the body has to be sniffed. Written
 * without indentation, a list of resource actions arrives as one unwrapped
 * line that no amount of syntax highlighting makes readable — parsing and
 * re-printing is what puts the line breaks in.
 *
 * Returning null means "render it the way we always did".
 */
export function prettyPrintJson(text: string): string | null {
  // The cheap gate, and the only type check needed: a body starting with
  // `{` or `[` either parses to an object/array or throws, so scalars are
  // rejected here rather than after the parse. HCL plans, the common case,
  // never reach JSON.parse at all. Testing the untrimmed string avoids
  // copying the whole body; JSON.parse tolerates the leading whitespace.
  if (text.length > MAX_PRETTY_JSON_BYTES || !/^\s*[{[]/.test(text)) return null;
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return null;
  }
}

export default function ArtifactContent({
  kind,
  artifact,
  operation,
  onPlanType,
}: Readonly<ArtifactContentProps>) {
  const [content, setContent] = useState<string | null>(null);
  const [files, setFiles] = useState<Record<string, string> | null>(null);
  // Names in `files` whose body is raw content, not a diff — the viewer
  // cannot tell from the text, so the store's metadata is carried across.
  const [newFiles, setNewFiles] = useState<ReadonlySet<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [applyFilter, setApplyFilter] = useState<ApplyFilterId>("all");
  const [importFilter, setImportFilter] = useState<ImportFilterId>("all");
  // Open by default: the targets answer "what is this plan scoped to?",
  // which is the question that brought the user here from the timeline.
  const [targetsOpen, setTargetsOpen] = useState(true);
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

  const changeFileName =
    kind === "change" ? (artifact as CodeChangeRef).file_name : "";

  // A notification sink, not a fetch input: kept in a ref so an
  // unmemoized prop from a caller cannot re-trigger the download.
  const onPlanTypeRef = useRef(onPlanType);
  useEffect(() => {
    onPlanTypeRef.current = onPlanType;
  });

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setContent(null);
    setFiles(null);
    setNewFiles(new Set());

    (async () => {
      try {
        if (kind === "change") {
          const { text, isNewFile } = await fetchArtifact(artifact.url);
          if (cancelled) return;
          setFiles({ [changeFileName]: text });
          setNewFiles(new Set(isNewFile ? [changeFileName] : []));
        } else {
          // Body and metadata come from the same response, so the plan's
          // flavour is free here — no ranged follow-up for an artifact
          // already on screen.
          const { text, planType } = await fetchArtifact(artifact.url);
          if (cancelled) return;
          setContent(text);
          if (planType) onPlanTypeRef.current?.(artifact.id, planType);
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
  }, [kind, artifact.id, artifact.url, changeFileName]);

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

  const complianceData: ComplianceReport | null = useMemo(() => {
    if (kind !== "compliance" || !content) return null;
    try {
      return JSON.parse(content);
    } catch {
      return null;
    }
  }, [kind, content]);

  // Everything that reaches the raw viewer: plans, and reports whose body
  // isn't the shape the report renderers expect. Keyed on `content`, which
  // the fetch effect writes once per artifact — so the parse does not
  // re-run when a filter tab or a detail overlay changes `searchParams`.
  // Gated on `reportData` and `complianceData` so a body the renderers
  // already claimed is never parsed twice; that second pass would be the
  // expensive one.
  const prettyContent = useMemo(
    () =>
      content && !reportData && !complianceData
        ? prettyPrintJson(content)
        : null,
    [content, reportData, complianceData],
  );

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

  if (loading) {
    return <Typography variant="subtitle2" component="div" className={styles.loading}>Loading artifact...</Typography>;
  }

  if (kind === "change") {
    if (!files) {
      return <Typography variant="subtitle2" component="div" className={styles.loading}>Failed to load artifact</Typography>;
    }
    return (
      <CodeBlock
        files={files}
        newFiles={newFiles}
        activeFile={changeFileName}
        showLineNumbers
        height="calc(100vh - 200px)"
      />
    );
  }

  if (content === null) {
    return <Typography variant="subtitle2" component="div" className={styles.loading}>Failed to load artifact</Typography>;
  }

  if (kind === "compliance" && complianceData) {
    return (
      <div className={styles.reportContainer}>
        <ComplianceSummaryCard report={complianceData} />
        <ComplianceViolations violations={complianceData.violations} />
        <ComplianceRules
          rules={complianceData.checked_rules}
          violations={complianceData.violations}
        />
      </div>
    );
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

  // The timeline row only had room for a count, so the addresses
  // themselves land here, where they can be read and copied.
  const planTargets =
    kind === "plan" ? ((artifact as TerraformPlanRef).targets ?? []) : [];

  return (
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
              <ExpandLessIcon className={styles.targetsToggleIcon} />
            ) : (
              <ExpandMoreIcon className={styles.targetsToggleIcon} />
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
      <CodeBlock
        code={prettyContent ?? content}
        // The sniffed result overrides the declared one here rather than
        // being threaded into getLanguage, which stays pure and
        // metadata-only.
        language={prettyContent ? "json" : getLanguage(kind, artifact)}
        showLineNumbers
        height={
          planTargets.length === 0
            ? EDITOR_HEIGHT
            : targetsOpen
              ? EDITOR_HEIGHT_TARGETS_OPEN
              : EDITOR_HEIGHT_TARGETS_CLOSED
        }
      />
    </>
  );
}
