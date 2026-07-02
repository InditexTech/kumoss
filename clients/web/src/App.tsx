import { useEffect, useMemo } from "react";
import type { ReactNode } from "react";
import { createTheme, ThemeProvider } from "@mui/material";
import { STORAGE_KEYS, THEME } from "@/constants";
import { AuthProvider } from "@/contexts/AuthContext";
import { ModeProvider } from "@/contexts/ModeContext";
import { AssistantMsgProvider } from "@/contexts/AssistantMsgContext";
import { NotificationProvider } from "@/contexts/NotificationContext";
import { BackgroundAnimation, ErrorBoundary } from "@/components/ui";
import { ShellProvider, useShell } from "@/contexts/ShellContext";
import { useBrowserNotification } from "@/hooks/useBrowserNotification";
import AppContent from "./AppContent";
import { getLocalItem } from "./services";

declare module "@mui/material/styles" {
  interface TypographyVariants {
    headline: React.CSSProperties;
    bodyText: React.CSSProperties;
    micro: React.CSSProperties;
    label: React.CSSProperties;
    subtitleSemiBold: React.CSSProperties;
  }
  interface TypographyVariantsOptions {
    headline?: React.CSSProperties;
    bodyText?: React.CSSProperties;
    micro?: React.CSSProperties;
    label?: React.CSSProperties;
    subtitleSemiBold?: React.CSSProperties;
  }
}

declare module "@mui/material/Typography" {
  interface TypographyPropsVariantOverrides {
    headline: true;
    bodyText: true;
    micro: true;
    label: true;
    subtitleSemiBold: true;
  }
}

function MuiThemeSync({ children }: Readonly<{ children: ReactNode }>) {
  const { isDark } = useShell();
  const theme = useMemo(
    () =>
      createTheme({
        palette: { mode: isDark ? "dark" : "light" },
        typography: {
          fontFamily: '"Inter", sans-serif',
          h1: { fontWeight: 300, fontSize: "clamp(29px, 2.5vw + 8px, 38px)", lineHeight: 1.21, letterSpacing: "-0.01em" },
          h2: { fontWeight: 300, fontSize: "clamp(22px, 2vw + 5px, 29px)", lineHeight: 1.21, letterSpacing: "-0.01em" },
          h3: { fontWeight: 300, fontSize: "19px", lineHeight: 1.25, letterSpacing: "0.01em" },
          h4: { fontWeight: 300, fontSize: "18px", lineHeight: 1.25, letterSpacing: "0.01em" },
          subtitle1: { fontWeight: 300, fontSize: "16px", lineHeight: 1.375, letterSpacing: "0.04em" },
          subtitle2: { fontWeight: 300, fontSize: "14px", lineHeight: 1.14, letterSpacing: "0.01em" },
          body1: { fontWeight: 300, fontSize: "16px", lineHeight: 1.25, letterSpacing: "0.01em" },
          body2: { fontWeight: 300, fontSize: "14px", lineHeight: 1.43, letterSpacing: "0.04em" },
          caption: { fontWeight: 300, fontSize: "12px", lineHeight: 1.33, letterSpacing: "0.04em", textTransform: "uppercase" as const },
          overline: { fontWeight: 300, fontSize: "13px", lineHeight: 1.38, letterSpacing: "0.08em", textTransform: "uppercase" as const },
          button: { fontWeight: 300, letterSpacing: "0.08em", textTransform: "uppercase" as const },
          headline: { fontWeight: 300, fontSize: "48px", lineHeight: "56px", letterSpacing: "-0.05em" },
          h5: { fontWeight: 300, fontSize: "24px", lineHeight: "32px", letterSpacing: "-0.01em" },
          bodyText: { fontWeight: 300, fontSize: "15px", lineHeight: 1.7, letterSpacing: "0" },
          micro: { fontWeight: 300, fontSize: "11px", lineHeight: 1.45, letterSpacing: "0.08em" },
          label: { fontWeight: 500, fontSize: "12px", lineHeight: 1.33, letterSpacing: "0.05em", textTransform: "uppercase" as const },
          subtitleSemiBold: { fontWeight: 500, fontSize: "14px", lineHeight: 1.14, letterSpacing: "0.01em" },
        },
      }),
    [isDark],
  );
  return <ThemeProvider theme={theme}>{children}</ThemeProvider>;
}

function BrowserNotificationInit() {
  const { requestPermission } = useBrowserNotification();
  useEffect(() => { requestPermission(); }, [requestPermission]);
  return null;
}

function App() {
  useEffect(() => {
    document.documentElement.style.setProperty(
      "color-scheme",
      getLocalItem(STORAGE_KEYS.THEME) === THEME.LIGHT
        ? THEME.LIGHT
        : THEME.DARK,
    );
  }, []);

  return (
    <ErrorBoundary>
      <AuthProvider>
        <ShellProvider>
          <MuiThemeSync>
            <NotificationProvider>
              <ModeProvider>
                <AssistantMsgProvider>
                  <BackgroundAnimation />
                  <div style={{ position: "relative", zIndex: 1, display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
                    <BrowserNotificationInit />
                    <AppContent />
                  </div>
                </AssistantMsgProvider>
              </ModeProvider>
            </NotificationProvider>
          </MuiThemeSync>
        </ShellProvider>
      </AuthProvider>
    </ErrorBoundary>
  );
}

export default App;
