// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { ButtonBase } from "@mui/material";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import SettingsIcon from "@mui/icons-material/Settings";
import PersonOutlineIcon from "@mui/icons-material/PersonOutline";
import PersonIcon from "@mui/icons-material/Person";
import { Authenticated } from "@/contexts/AuthContext";
import { useCurrentView } from "@/hooks/useCurrentView";
import { SupportButton } from "@/components/ui";
import ConfigurationModal from "@/components/ConfigurationModal/ConfigurationModal";
// DISABLED: SupportModal posts to /api/v1/notifications, which has no
// backend route. Re-enable the commented blocks below when it returns.
// import SupportModal from "@/components/SupportModal/SupportModal";
import ModeDropdown from "./ModeDropdown/ModeDropdown";
import styles from "./Header.module.css";

function Header() {
  const navigate = useNavigate();
  const location = useLocation();
  const view = useCurrentView();
  const [configOpen, setConfigOpen] = useState(false);
  // const [supportOpen, setSupportOpen] = useState(false);
  const modeDisabled = view !== null && view !== "wizard";

  return (
    <>
      <header className={styles.header}>
        <div className={styles.logo}>
          <a
            href="/home"
            onClick={(e) => {
              // SPA navigation: a full reload would replay the greeting
              // splash, which should only show on an actual page refresh.
              // Preserve default browser behaviors for new-tab/new-window clicks.
              if (
                e.button !== 0 ||
                e.metaKey ||
                e.ctrlKey ||
                e.shiftKey ||
                e.altKey
              ) {
                return;
              }
              e.preventDefault();
              navigate("/home", { state: { resetWizard: true } });
            }}
          >
            <span>NEBULA</span>
            <span>.AI</span>
          </a>
        </div>

        <div className={styles.rightSection}>
          <Authenticated>
            <ModeDropdown disabled={modeDisabled} />
            <div className={styles.separator} />
            <ButtonBase
              onClick={() => setConfigOpen(true)}
              className={styles.iconButton}
              aria-label="Configuration"
            >
              {configOpen ? (
                <SettingsIcon className={styles.headerIcon} />
              ) : (
                <SettingsOutlinedIcon className={styles.headerIcon} />
              )}
            </ButtonBase>
            <ButtonBase
              onClick={() => navigate("/user")}
              className={styles.iconButton}
              aria-label="User information"
            >
              {location.pathname === "/user" ? (
                <PersonIcon className={styles.headerIcon} />
              ) : (
                <PersonOutlineIcon className={styles.headerIcon} />
              )}
            </ButtonBase>
            <SupportButton variant="icon" />
            {/* {hasWizardData ? (
              <SupportButton variant="icon" />
            ) : (
              <ButtonBase
                onClick={() => setSupportOpen(true)}
                className={styles.iconButton}
                aria-label="Support"
              >
                {supportOpen ? (
                  <ChatBubbleIcon className={styles.headerIcon} />
                ) : (
                  <ChatBubbleOutlineIcon className={styles.headerIcon} />
                )}
              </ButtonBase>
            )} */}
          </Authenticated>
        </div>
      </header>
      {configOpen && (
        <ConfigurationModal onClose={() => setConfigOpen(false)} />
      )}
      {/* {supportOpen && (
        <SupportModal onClose={() => setSupportOpen(false)} />
      )} */}
    </>
  );
}

export default Header;
