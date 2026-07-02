import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { ButtonBase } from "@mui/material";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import SettingsIcon from "@mui/icons-material/Settings";
import PersonOutlineIcon from "@mui/icons-material/PersonOutline";
import PersonIcon from "@mui/icons-material/Person";
import ChatBubbleOutlineIcon from "@mui/icons-material/ChatBubbleOutline";
import ChatBubbleIcon from "@mui/icons-material/ChatBubble";
import { Authenticated } from "@/contexts/AuthContext";
import { useSession } from "@/contexts/SessionContext";
import { useCurrentView } from "@/hooks/useCurrentView";
import { SupportButton } from "@/components/ui";
import ConfigurationModal from "@/components/ConfigurationModal/ConfigurationModal";
import SupportModal from "@/components/SupportModal/SupportModal";
import ModeDropdown from "./ModeDropdown/ModeDropdown";
import styles from "./Header.module.css";

function Header() {
  const navigate = useNavigate();
  const location = useLocation();
  const { session } = useSession();
  const view = useCurrentView();
  const [configOpen, setConfigOpen] = useState(false);
  const [supportOpen, setSupportOpen] = useState(false);
  const modeDisabled = view !== null && view !== "wizard";

  const hasWizardData = !!(
    session.firstQuery || session.userQueries.length > 0
  );

  const openConfig = () => {
    setConfigOpen(true);
    setSupportOpen(false);
  };

  const openSupport = () => {
    setConfigOpen(false);
    setSupportOpen(true);
  };

  return (
    <>
      <header className={styles.header}>
        <div className={styles.logo}>
          <a href="/">
            <span>NEBULA</span>
            <span>.AI</span>
          </a>
        </div>

        <div className={styles.rightSection}>
          <Authenticated>
            <ModeDropdown disabled={modeDisabled} />
            <div className={styles.separator} />
            <ButtonBase
              onClick={openConfig}
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
            {hasWizardData ? (
              <SupportButton variant="icon" />
            ) : (
              <ButtonBase
                onClick={openSupport}
                className={styles.iconButton}
                aria-label="Support"
              >
                {supportOpen ? (
                  <ChatBubbleIcon className={styles.headerIcon} />
                ) : (
                  <ChatBubbleOutlineIcon className={styles.headerIcon} />
                )}
              </ButtonBase>
            )}
          </Authenticated>
        </div>
      </header>
      {configOpen && (
        <ConfigurationModal onClose={() => setConfigOpen(false)} />
      )}
      {supportOpen && (
        <SupportModal onClose={() => setSupportOpen(false)} />
      )}
    </>
  );
}

export default Header;
