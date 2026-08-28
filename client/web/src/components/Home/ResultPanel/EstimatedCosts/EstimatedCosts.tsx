// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import Typography from "@mui/material/Typography";
import { PageOverlay } from "@/components/ui";
import {
  formatMonthlyCost,
  summaryCosts,
  PRICING_MODEL_LABELS,
} from "../resultPanelUtils";
import type { TerraformReport, CostBreakdownItem } from "@/types";
import styles from "./EstimatedCosts.module.css";

type CostsData = NonNullable<TerraformReport["estimated_costs"]>;

export function EstimatedCostsCard({ costs }: { costs: CostsData }) {
  const { total_fixed_monthly_cost, currency, introduction_paragraph } = costs;
  if (typeof total_fixed_monthly_cost !== "number") return null;

  const parsed = summaryCosts(total_fixed_monthly_cost, currency);

  return (
    <div className={styles.costsCard}>
      <Typography variant="h4" className={styles.costsLabel}>Estimated Cost</Typography>
      <div className={styles.costsInline}>
        {parsed.map(({ amount, period }) => (
          <span key={period} className={styles.costInlineGroup}>
            <Typography variant="headline" component="span" className={styles.costInlineAmount}>{amount}</Typography>
            <Typography variant="subtitle2" component="span" className={styles.costInlinePeriod}>
              /{period.toLowerCase()}
            </Typography>
          </span>
        ))}
      </div>
      {introduction_paragraph && (
        <Typography variant="subtitle2" className={styles.costsDescription}>{introduction_paragraph}</Typography>
      )}
    </div>
  );
}

export function CostsDetail({
  costs,
  onClose,
}: {
  costs: CostsData;
  onClose: () => void;
}) {
  const { total_fixed_monthly_cost, currency, introduction_paragraph, breakdown } = costs;
  const totals =
    typeof total_fixed_monthly_cost === "number"
      ? summaryCosts(total_fixed_monthly_cost, currency)
      : null;
  const items = (breakdown ?? []).filter(
    (item) => typeof item.fixed_monthly_cost === "number",
  );

  return (
    <PageOverlay title="Estimated Cost" onClose={onClose}>
      <div className={styles.costSummaryTable}>
        {totals && (
          <div className={styles.costSummaryRow}>
            <Typography variant="label" component="span" className={styles.costSummaryLabel}>Total</Typography>
            <div className={styles.costTotalValues}>
              {totals.map(({ amount, period }) => (
                <div key={period} className={styles.costTotalGroup}>
                  <span className={styles.costTotalAmount}>{amount}</span>
                  <span className={styles.costTotalPeriod}>{period}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {introduction_paragraph && (
          <div className={styles.costSummaryRow}>
            <Typography variant="label" component="span" className={styles.costSummaryLabel}>Details</Typography>
            <Typography variant="body2" component="span" className={styles.costSummaryValue}>
              {introduction_paragraph}
            </Typography>
          </div>
        )}
      </div>

      {items.length > 0 && (
        <div className={styles.breakdownSection}>
          <Typography variant="h5" component="h3" className={styles.breakdownTitle}>Cost Breakdown</Typography>
          <div className={styles.breakdownGrid}>
            {items.map((item: CostBreakdownItem, i: number) => {
              const modelLabel = PRICING_MODEL_LABELS[item.pricing_model];
              const isNegative = item.fixed_monthly_cost < 0;
              return (
                <div key={i} className={styles.breakdownItem}>
                  <Typography variant="label" component="h4" className={styles.breakdownResourceType}>
                    {item.resource_type}
                  </Typography>
                  <p className={styles.breakdownCostLabel}>Estimated Cost</p>
                  {modelLabel ? (
                    <Typography
                      variant="h2"
                      className={`${styles.breakdownValue} ${styles.breakdownValueMuted}`}
                    >
                      {modelLabel}
                    </Typography>
                  ) : (
                    <>
                      <Typography
                        variant="h2"
                        className={`${styles.breakdownValue} ${isNegative ? styles.breakdownValueNegative : ""}`}
                      >
                        {formatMonthlyCost(item.fixed_monthly_cost, currency)}
                      </Typography>
                      <Typography variant="label" className={styles.breakdownUnit}>PER MONTH</Typography>
                    </>
                  )}
                  <Typography variant="body2" className={styles.breakdownAdditionalText}>
                    {item.notes}
                  </Typography>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </PageOverlay>
  );
}
