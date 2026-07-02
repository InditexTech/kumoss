import { useState, useEffect } from "react";
import Fade from "@mui/material/Fade";
import Typography from "@mui/material/Typography";
import { AssistantAnimation } from "@/components/ui/AssistantAnimation/AssistantAnimation";
import { useAuth } from "@/contexts/AuthContext";
import styles from "./IntroScreen.module.css";

type IntroPhase = 0 | 1 | 2;

const PHASE_DURATION_MS = 2500;
const FADE_DURATION_MS = 600;

function capitalizeFirst(str: string): string {
  return str.charAt(0).toUpperCase() + str.slice(1);
}

interface IntroScreenProps {
  onComplete?: () => void;
}

const IntroScreen = ({ onComplete }: IntroScreenProps) => {
  const { user } = useAuth();
  const [phase, setPhase] = useState<IntroPhase>(0);

  const firstName = capitalizeFirst(user?.name?.split(/[._-]/)[0] ?? "there");

  const messages = [`Hello, ${firstName}`, "Welcome to Nebula AI"];

  useEffect(() => {
    const timer1 = setTimeout(() => setPhase(1), PHASE_DURATION_MS);
    const timer2 = setTimeout(() => setPhase(2), PHASE_DURATION_MS * 2);
    return () => {
      clearTimeout(timer1);
      clearTimeout(timer2);
    };
  }, []);

  useEffect(() => {
    if (phase === 2) {
      onComplete?.();
    }
  }, [phase, onComplete]);

  return (
    <div className={styles.container}>
      <AssistantAnimation type="standby" size={180} />

      <Fade in={phase === 0} timeout={FADE_DURATION_MS} unmountOnExit>
        <Typography variant="headline" className={styles.message}>{messages[0]}</Typography>
      </Fade>

      <Fade in={phase === 1} timeout={FADE_DURATION_MS} unmountOnExit>
        <Typography variant="headline" className={styles.message}>{messages[1]}</Typography>
      </Fade>
    </div>
  );
};

export default IntroScreen;
