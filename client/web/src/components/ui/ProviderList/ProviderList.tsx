// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import Tooltip from "@mui/material/Tooltip";
import { providerLabel } from "@/constants/providers";
import ProviderIcon from "../ProviderIcon/ProviderIcon";
import styles from "./ProviderList.module.css";

interface ProviderListProps {
  /** Terraform provider type names, in the order the session lists them. */
  providers: readonly string[];
  /** `chips`: icon + type name; `icons`: icon only, the name in a tooltip. */
  variant?: "chips" | "icons";
  /** Shown when there are no providers (e.g. setup has not run yet). */
  empty?: string | null;
  className?: string;
}

/**
 * A session's providers: known ones (azurerm, google, aws, oci,
 * kubernetes, vsphere) with their logo, any other with a generic icon.
 */
export default function ProviderList({
  providers,
  variant = "chips",
  empty = "—",
  className,
}: ProviderListProps) {
  if (providers.length === 0) {
    return empty ? <span className={styles.empty}>{empty}</span> : null;
  }

  return (
    <ul
      className={`${styles.list} ${className ?? ""}`}
      aria-label="Providers"
    >
      {providers.map((name) => {
        const label = providerLabel(name);
        const title = label === name ? name : `${label} (${name})`;
        return (
          <Tooltip key={name} title={title} arrow>
            <li
              className={variant === "icons" ? styles.iconOnly : styles.chip}
              aria-label={variant === "icons" ? name : undefined}
            >
              <ProviderIcon provider={name} className={styles.icon} aria-hidden="true" />
              {variant === "chips" && <span className={styles.name}>{name}</span>}
            </li>
          </Tooltip>
        );
      })}
    </ul>
  );
}
