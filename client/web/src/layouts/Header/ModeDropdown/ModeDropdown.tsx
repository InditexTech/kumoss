// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { Select, MenuItem } from "@mui/material";
import { useAuth } from "@/contexts/AuthContext";
import { useMode } from "@/contexts/ModeContext";
import { MODE_OPTIONS } from "@/constants/modes";
import { operationRoleAtLeast } from "@/types/api";
import type { Mode } from "@/types/ui";
import { MODE } from "@/types/ui";
import type { SelectChangeEvent } from "@mui/material";
import styles from "./ModeDropdown.module.css";

const DEVOPS_ONLY_MODES: Mode[] = [MODE.DRIFT, MODE.PARTIAL_DRIFT, MODE.IMPORT];
const DEVOPS_HINT = "Requires the devops operation role.";

const selectSx = {
  fontSize: "14px",
  fontWeight: 300,
  fontFeatureSettings: "'tnum' on, 'lnum' on",
  borderRadius: 0,
  minWidth: { xs: 0, sm: 220 },
  "& .MuiOutlinedInput-notchedOutline": {
    border: "none",
  },
  "& .MuiSelect-select": {
    padding: "8px 12px",
  },
  "& .MuiSelect-icon": {
    color: "light-dark(var(--text-color-light), var(--text-color-dark))",
  },
  "&.Mui-disabled": {
    opacity: 1,
    cursor: "default",
    "& .MuiSelect-select": {
      color: "light-dark(var(--text-color-light), var(--text-color-dark))",
      WebkitTextFillColor: "light-dark(var(--text-color-light), var(--text-color-dark))",
    },
    "& .MuiSelect-icon": {
      display: "none",
    },
  },
} as const;

const menuPropsSx = {
  slotProps: {
    paper: {
      sx: {
        borderRadius: 0,
        border: "1px solid",
        borderColor: "light-dark(var(--color-border), rgba(255, 255, 255, 0.18))",
        boxShadow:
          "0 10px 15px -3px light-dark(rgba(0, 0, 0, 0.1), rgba(0, 0, 30, 0.5)), 0 4px 6px -2px light-dark(rgba(0, 0, 0, 0.05), rgba(0, 0, 30, 0.35))",
        background: "var(--color-surface)",
        padding: "16px 0",
        "& .MuiList-root": { padding: 0 },
        "& .MuiMenuItem-root:hover": {
          backgroundColor:
            "light-dark(rgba(0, 0, 0, 0.03), rgba(255, 255, 255, 0.05))",
        },
        "& .MuiMenuItem-root.Mui-focusVisible": {
          backgroundColor:
            "light-dark(rgba(0, 0, 0, 0.05), rgba(255, 255, 255, 0.08))",
        },
        "& .MuiMenuItem-root.Mui-selected": {
          backgroundColor:
            "light-dark(rgba(0, 0, 0, 0.05), rgba(255, 255, 255, 0.08))",
        },
        "& .MuiMenuItem-root.Mui-selected:hover": {
          backgroundColor:
            "light-dark(rgba(0, 0, 0, 0.07), rgba(255, 255, 255, 0.11))",
        },
      },
    },
  },
};

export default function ModeDropdown({ disabled = false }: { disabled?: boolean }) {
  const { mode, setMode } = useMode();
  const { operationRole } = useAuth();
  const isDevops = operationRoleAtLeast(operationRole, "devops");

  const handleChange = (event: SelectChangeEvent<string>) => {
    setMode(event.target.value as Mode);
  };

  const currentOption = MODE_OPTIONS.find((opt) => opt.value === mode);

  return (
    <Select
      name="mode"
      value={mode}
      onChange={handleChange}
      disabled={disabled}
      className={styles.dropdown}
      sx={selectSx}
      MenuProps={menuPropsSx}
      renderValue={() => {
        if (!currentOption) return null;
        return (
          <span className={styles.selectedLabel}>{currentOption.label}</span>
        );
      }}
    >
      {MODE_OPTIONS.map(({ value, label, description }) => {
        const locked = DEVOPS_ONLY_MODES.includes(value) && !isDevops;
        return (
          <MenuItem
            key={value}
            value={value}
            className={styles.menuItem}
            disabled={locked}
          >
            <div className={styles.menuItemContent}>
              <span className={styles.menuItemLabel}>{label}</span>
              <span className={styles.menuItemDescription}>
                {locked ? DEVOPS_HINT : description}
              </span>
            </div>
          </MenuItem>
        );
      })}
    </Select>
  );
}
