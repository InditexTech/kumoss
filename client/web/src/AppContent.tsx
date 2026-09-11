// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useEffect } from "react";
import LoginPage from "./pages/LoginPage";
import Header from "./layouts/Header/Header";
import { useAuth } from "./contexts/AuthContext";
import GreetingScreen from "./components/ui/GreetingScreen/GreetingScreen";
import Footer from "./layouts/Footer/Footer";
import AppRouter from "./router";

export default function AppContent() {
  const { isAuthenticated, isLoading } = useAuth();
  const [showGreeting, setShowGreeting] = useState(true);

  const SPLASH_DURATION_MS = 2000;

  useEffect(() => {
    const timer = setTimeout(() => setShowGreeting(false), SPLASH_DURATION_MS);
    return () => clearTimeout(timer);
  }, []);

  if (showGreeting || isLoading) {
    return <GreetingScreen />;
  }

  if (!isAuthenticated) {
    return <LoginPage />;
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        flex: 1,
        minHeight: 0,
      }}
    >
      <Header />
      <AppRouter />
      <Footer />
    </div>
  );
}
