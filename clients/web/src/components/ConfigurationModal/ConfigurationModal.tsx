import { ButtonBase, Divider, Select, MenuItem, Tooltip } from "@mui/material";
import type { SelectChangeEvent } from "@mui/material";
import { useMode } from "@/contexts/ModeContext";
import { useShell } from "@/contexts/ShellContext";
import { useSession } from "@/contexts/SessionContext";
import { useNotification } from "@/contexts/NotificationContext";
import { useBrowserNotification } from "@/hooks/useBrowserNotification";
import { MODE_OPTIONS } from "@/constants/modes";
import { Modal } from "@/components/ui";
import styles from "./ConfigurationModal.module.css";

const selectSx = {
  fontSize: "14px",
  fontWeight: 300,
  textTransform: "uppercase" as const,
  letterSpacing: "1px",
  borderRadius: 0,
  "& .MuiOutlinedInput-notchedOutline": { border: "none" },
  "& .MuiSelect-select": { padding: "4px 8px", paddingRight: "28px !important" },
  "& .MuiSelect-icon": {
    color: "light-dark(var(--text-color-light), var(--text-color-dark))",
    fontSize: "18px",
  },
} as const;

const menuPropsSx = {
  slotProps: {
    paper: {
      sx: {
        borderRadius: 0,
        border: "1px solid",
        borderColor: "light-dark(var(--color-border), var(--color-border))",
        boxShadow: "0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -2px rgba(0,0,0,0.05)",
        background: "light-dark(#ffffff, #1a1a1a)",
        "& .MuiList-root": { padding: 0 },
        "& .MuiMenuItem-root": {
          fontSize: "14px",
          fontWeight: 300,
          letterSpacing: "1px",
          textTransform: "uppercase",
        },
      },
    },
  },
};

const ICON_CLASS_MAP: Record<string, string> = {
  generate: styles.generateIcon,
  drift: styles.driftIcon,
  partial_drift: styles.partialDriftIcon,
  import: styles.importIcon,
};

interface ConfigurationModalProps {
  onClose: () => void;
}

export default function ConfigurationModal({ onClose }: ConfigurationModalProps) {
  const { mode, setMode } = useMode();
  const { isDark, setIsDark } = useShell();
  const { session } = useSession();
  const { permission, requestPermission } = useBrowserNotification();
  const { showNotification } = useNotification();

  return (
    <Modal title="Configuration" onClose={onClose}>
      {/* Operation Mode — kept for future extraction to a separate component
      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Operation Mode</h2>
        <div className={styles.optionsList}>
          {MODE_OPTIONS.map(({ value, label, icon: Icon }) => (
            <ButtonBase
              key={value}
              className={`${styles.optionItem} ${mode === value ? styles.optionItemActive : ""}`}
              onClick={() => setMode(value)}
            >
              <Icon
                className={`${styles.optionIcon} ${ICON_CLASS_MAP[value] || ""}`}
              />
              <span className={styles.optionText}>{label}</span>
            </ButtonBase>
          ))}
        </div>
      </section>

      <Divider />
      */}

      <div className={styles.settingRow}>
        <div className={styles.settingText}>
          <span className={styles.settingTitle}>Theme</span>
          <span className={styles.settingDescription}>Switch between light and dark mode</span>
        </div>
        <Select
          value={isDark ? "dark" : "light"}
          onChange={(e: SelectChangeEvent) => setIsDark(e.target.value === "dark")}
          sx={selectSx}
          MenuProps={menuPropsSx}
        >
          <MenuItem value="light">LIGHT</MenuItem>
          <MenuItem value="dark">DARK</MenuItem>
        </Select>
      </div>

      <Divider />

      <div className={styles.settingRow}>
        <div className={styles.settingText}>
          <span className={styles.settingTitle}>Notifications</span>
          <span className={styles.settingDescription}>Enable browser push notifications</span>
        </div>
        <Tooltip
          title={permission === "granted" ? "To disable notifications, revoke permission in your browser's site settings" : ""}
          placement="left"
          arrow
        >
          <span>
            <Select
              value={permission === "granted" ? "enabled" : "disabled"}
              disabled={permission === "granted"}
              onChange={async (e: SelectChangeEvent) => {
                if (e.target.value === "enabled") {
                  if (permission === "denied") {
                    showNotification(
                      "warning",
                      "Notifications were blocked. Please enable them in your browser's site settings.",
                    );
                    return;
                  }
                  await requestPermission();
                }
              }}
              sx={selectSx}
              MenuProps={menuPropsSx}
            >
              <MenuItem value="enabled">ENABLED</MenuItem>
              <MenuItem value="disabled">DISABLED</MenuItem>
            </Select>
          </span>
        </Tooltip>
      </div>

      {/* Session info — kept for future extraction to a separate component
      <Divider />

      <section className={styles.section} style={{ marginTop: 40 }}>
        <h2 className={styles.sectionTitle}>Session</h2>
        <div className={styles.sessionGrid}>
          <div className={styles.sessionCard}>
            <p className={styles.sessionLabel}>Project</p>
            <p className={styles.sessionValue}>{session.project || "—"}</p>
          </div>
          <div className={styles.sessionCard}>
            <p className={styles.sessionLabel}>Cloud</p>
            <p className={styles.sessionValue}>{session.cloud || "—"}</p>
          </div>
          <div className={styles.sessionCard}>
            <p className={styles.sessionLabel}>Environment</p>
            <p className={styles.sessionValue}>
              {session.environment || "—"}
            </p>
          </div>
          <div className={styles.sessionCard}>
            <p className={styles.sessionLabel}>Session ID</p>
            <p className={styles.sessionValue}>{session.session_id || "—"}</p>
          </div>
        </div>
      </section>
      */}
    </Modal>
  );
}
