// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import Fade from "@mui/material/Fade";
import styles from "./GreetingScreen.module.css";

const GreetingScreen = () => {
  return (
    <Fade in timeout={500}>
      <div className={`${styles.greetingScreen} ${styles.greetingContainer}`}>
        <p className={styles.greetingTitle}>NEBULA</p>
      </div>
    </Fade>
  );
};

export default GreetingScreen;
