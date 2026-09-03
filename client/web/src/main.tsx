// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { AuthProvider as OidcProvider } from "react-oidc-context";
import { SessionProvider } from "@/contexts/SessionContext";
import { buildOidcConfig, isOidcEnabled, loadAuthConfig } from "@/services/auth";
import "./index.css";
import App from "./App";

function BootstrapError() {
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 16,
        fontFamily: '"Inter", sans-serif',
        fontWeight: 300,
      }}
    >
      <p>Could not load the application configuration.</p>
      <button onClick={() => window.location.reload()}>Retry</button>
    </div>
  );
}

async function bootstrap() {
  const root = createRoot(document.getElementById("root")!);

  try {
    await loadAuthConfig();
  } catch {
    root.render(<BootstrapError />);
    return;
  }

  const app = (
    <BrowserRouter>
      <SessionProvider>
        <App />
      </SessionProvider>
    </BrowserRouter>
  );

  root.render(
    isOidcEnabled() ? (
      <OidcProvider {...buildOidcConfig()}>{app}</OidcProvider>
    ) : (
      app
    ),
  );
}

bootstrap();
