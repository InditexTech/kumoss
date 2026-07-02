import { useState, useEffect, useCallback } from "react";
import LoginPage from "./pages/LoginPage";
import Header from "./layouts/Header/Header";
import { useAuth } from "./contexts/AuthContext";
import GreetingScreen from "./components/ui/GreetingScreen/GreetingScreen";
import IntroScreen from "./components/ui/IntroScreen/IntroScreen";
import Footer from "./layouts/Footer/Footer";
import AppRouter from "./router";

const SPLASH_DURATION_MS = 2000;

export default function AppContent() {
  const { isAuthenticated } = useAuth();
  const [showGreeting, setShowGreeting] = useState(true);
  const [introComplete, setIntroComplete] = useState(false);
  const [showIntro, setShowIntro] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setShowGreeting(false), SPLASH_DURATION_MS);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!showGreeting && isAuthenticated && !introComplete) {
      setShowIntro(true);
    }
  }, [showGreeting, isAuthenticated, introComplete]);

  const handleIntroComplete = useCallback(() => {
    setShowIntro(false);
    setIntroComplete(true);
  }, []);

  if (showGreeting) {
    return <GreetingScreen />;
  }

  if (!isAuthenticated) {
    return <LoginPage />;
  }

  if (showIntro) {
    return (
      <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
        <Header />
        <IntroScreen onComplete={handleIntroComplete} />
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
      <Header />
      <AppRouter />
      <Footer />
    </div>
  );
}
