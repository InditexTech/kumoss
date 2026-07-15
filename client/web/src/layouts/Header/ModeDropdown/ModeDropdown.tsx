// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { Select, MenuItem } from "@mui/material";
import { useMode } from "@/contexts/ModeContext";
import { MODE_OPTIONS } from "@/constants/modes";
import type { Mode } from "@/types/ui";
import type { SelectChangeEvent } from "@mui/material";
import styles from "./ModeDropdown.module.css";

const selectSx = {
  fontSize: "14px",
  fontWeight: 300,
  fontFeatureSettings: "'tnum' on, 'lnum' on",
  borderRadius: 0,
  minWidth: 220,
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
        borderColor: "light-dark(var(--color-border), var(--color-border))",
        boxShadow:
          "0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)",
        background: "light-dark(#ffffff, #1a1a1a)",
        padding: "16px",
        "& .MuiList-root": { padding: 0 },
      },
    },
  },
};

export default function ModeDropdown({ disabled = false }: { disabled?: boolean }) {
  const { mode, setMode } = useMode();

  const handleChange = (event: SelectChangeEvent<string>) => {
    setMode(event.target.value as Mode);
  };

  const currentOption = MODE_OPTIONS.find((opt) => opt.value === mode);

  return (
    <Select
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
      {MODE_OPTIONS.map(({ value, label, description }) => (
        <MenuItem key={value} value={value} className={styles.menuItem}>
          <div className={styles.menuItemContent}>
            <span className={styles.menuItemLabel}>{label}</span>
            {description && (
              <span className={styles.menuItemDescription}>{description}</span>
            )}
          </div>
        </MenuItem>
      ))}
    </Select>
  );
}
