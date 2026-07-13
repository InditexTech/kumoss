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
export type { FilterId, DetailView } from "./ResultPanel/resultPanelUtils";
