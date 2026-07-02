import Typography from "@mui/material/Typography";
import { PageOverlay } from "@/components/ui";
import { parseCostValue, parseSummaryCosts } from "../resultPanelUtils";
import type { TerraformReport, CostBreakdownItem } from "@/types";
import styles from "./EstimatedCosts.module.css";

type CostsData = NonNullable<TerraformReport["estimated_costs"]>;

export function EstimatedCostsCard({ costs }: { costs: CostsData }) {
  const { banner, introduction_paragraph } = costs;
  if (!banner) return null;

  const parsed = parseSummaryCosts(banner.summary);

  return (
    <div className={styles.costsCard}>
      <Typography variant="h4" className={styles.costsLabel}>Estimated Cost</Typography>
      {parsed ? (
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
      ) : (
        <h3 className={styles.costsSummary}>{banner.summary}</h3>
      )}
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
  const { banner, introduction_paragraph, breakdown } = costs;
  const summaryCosts = banner ? parseSummaryCosts(banner.summary) : null;

  return (
    <PageOverlay title="Estimated Cost" onClose={onClose}>
      <div className={styles.costSummaryTable}>
        {summaryCosts ? (
          <div className={styles.costSummaryRow}>
            <Typography variant="label" component="span" className={styles.costSummaryLabel}>Total</Typography>
            <div className={styles.costTotalValues}>
              {summaryCosts.map(({ amount, period }) => (
                <div key={period} className={styles.costTotalGroup}>
                  <span className={styles.costTotalAmount}>{amount}</span>
                  <span className={styles.costTotalPeriod}>{period}</span>
                </div>
              ))}
            </div>
          </div>
        ) : banner ? (
          <div className={styles.costSummaryRow}>
            <Typography variant="label" component="span" className={styles.costSummaryLabel}>Total</Typography>
            <Typography variant="body2" component="span" className={styles.costSummaryValue}>{banner.summary}</Typography>
          </div>
        ) : null}

        {banner && (
          <div className={styles.costSummaryRow}>
            <Typography variant="label" component="span" className={styles.costSummaryLabel}>Description</Typography>
            <Typography variant="body2" component="span" className={styles.costSummaryValue}>{banner.summary}</Typography>
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

      {breakdown && breakdown.length > 0 && (
        <div className={styles.breakdownSection}>
          <Typography variant="h5" component="h3" className={styles.breakdownTitle}>Cost Breakdown</Typography>
          <div className={styles.breakdownGrid}>
            {breakdown.map((item: CostBreakdownItem, i: number) => {
              const parsed = parseCostValue(item.details.estimated_cost);
              const isNegative = parsed.value.includes("-");
              return (
                <div key={i} className={styles.breakdownItem}>
                  <Typography variant="label" component="h4" className={styles.breakdownResourceType}>
                    {item.resource_type}
                  </Typography>
                  <p className={styles.breakdownCostLabel}>Estimated Cost</p>
                  <Typography
                    variant="h2"
                    className={`${styles.breakdownValue} ${isNegative ? styles.breakdownValueNegative : ""}`}
                  >
                    {parsed.value}
                  </Typography>
                  {parsed.unit && (
                    <Typography variant="label" className={styles.breakdownUnit}>{parsed.unit}</Typography>
                  )}
                  <Typography variant="body2" className={styles.breakdownAdditionalText}>
                    {item.details.additional_details}
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
