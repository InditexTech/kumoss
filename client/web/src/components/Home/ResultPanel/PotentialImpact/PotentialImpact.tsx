// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import Typography from "@mui/material/Typography";
import PageOverlay from "@/components/ui/PageOverlay/PageOverlay";
import { getLevelLabel } from "../resultPanelUtils";
import type { TerraformReport, BulletPoint } from "@/types";
import styles from "./PotentialImpact.module.css";

type ImpactData = NonNullable<TerraformReport["potential_impact"]>;

export function PotentialImpactCard({ impact }: { impact: ImpactData }) {
  const { banner, summary } = impact;
  if (!banner) return null;

  const level = banner.level as "high" | "medium" | "low";

  return (
    <div className={styles.impactCard}>
      <Typography variant="h4" className={styles.impactLabel}>Potential Impact</Typography>
      <Typography variant="headline" component="h2" className={`${styles.impactLevel} ${styles[level] || ""}`}>
        {getLevelLabel(level)}
      </Typography>
      {(summary || banner.description) && (
        <Typography variant="subtitle2" className={styles.impactDescription}>
          {summary || banner.description}
        </Typography>
      )}
    </div>
  );
}

export function ImpactDetail({
  impact,
  onClose,
}: {
  impact: ImpactData;
  onClose: () => void;
}) {
  const { banner, summary, bullet_points } = impact;
  const level = (banner?.level ?? "low") as "high" | "medium" | "low";

  return (
    <PageOverlay title="Potential Impact" onClose={onClose}>
      <div className={styles.impactGrid}>
        {banner && (
          <>
            <Typography variant="label" className={styles.impactSectionLabel}>STATUS</Typography>
            <Typography variant="bodyText" className={`${styles.impactStatusValue} ${styles[level] || ""}`}>
              {getLevelLabel(level)}
            </Typography>
          </>
        )}

        {banner?.title && (
          <>
            <Typography variant="label" className={styles.impactSectionLabel}>DESCRIPTION</Typography>
            <Typography variant="body2" className={styles.impactSectionBody}>{banner.title}</Typography>
          </>
        )}

        <Typography variant="label" className={styles.impactSectionLabel}>DETAILS</Typography>
        <div className={styles.impactDetailsValue}>
          {(summary || banner?.description) && (
            <Typography variant="body2" className={styles.impactSectionBody}>
              {summary || banner?.description}
            </Typography>
          )}

          {banner?.description &&
            summary &&
            banner.description !== summary && (
              <Typography variant="body2" className={styles.impactSectionBody}>{banner.description}</Typography>
            )}

          {bullet_points &&
            bullet_points.length > 0 &&
            bullet_points.map((point: BulletPoint, i: number) => (
              <div key={i} className={styles.impactBulletItem}>
                <Typography variant="subtitleSemiBold" className={styles.impactBulletTitle}>
                  <span className={styles.impactBulletDot}>·</span>
                  {point.title}
                </Typography>
                <p className={styles.impactBulletDescription}>
                  {point.description}
                </p>
              </div>
            ))}
        </div>
      </div>
    </PageOverlay>
  );
}
