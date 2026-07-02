import Fade from "@mui/material/Fade";
import styles from "./GreetingScreen.module.css";

const GreetingScreen = () => {
  return (
    <Fade in timeout={500}>
      <div className={`${styles.greetingScreen} ${styles.greetingContainer}`}>
        <p className={styles.greetingTitle}>
          <span>NEBULA</span>
          <span>.AI</span>
        </p>
      </div>
    </Fade>
  );
};

export default GreetingScreen;
