// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

export { default as ChangesTable } from "./ResultPanel/ChangesTable/ChangesTable";
export { default as ChangeDetail } from "./ResultPanel/ChangeDetail/ChangeDetail";
export {
  PotentialImpactCard,
  ImpactDetail,
} from "./ResultPanel/PotentialImpact/PotentialImpact";
export {
  EstimatedCostsCard,
  CostsDetail,
} from "./ResultPanel/EstimatedCosts/EstimatedCosts";
export {
  DriftChangesList,
  DriftLeftovers,
  DriftResourceDetail,
} from "./ResultPanel/DriftReport/DriftReport";
export {
  ApplyChangesList,
  ApplyResourceDetail,
  ApplyRecommendations,
} from "./ResultPanel/ApplyReport/ApplyReport";
export type { ApplyFilterId } from "./ResultPanel/ApplyReport/ApplyReport";
export {
  ImportedResourcesList,
  ImportExclusions,
  ImportStateAlignment,
  ImportedResourceDetail,
} from "./ResultPanel/ImportReport/ImportReport";
export type { ImportFilterId } from "./ResultPanel/ImportReport/ImportReport";
export {
  hasStructuredCosts,
  reportStatusVariant,
} from "./ResultPanel/resultPanelUtils";
export type { FilterId, DetailView } from "./ResultPanel/resultPanelUtils";
