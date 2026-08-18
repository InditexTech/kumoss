// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import styles from "./BackgroundAnimation.module.css";
import backgroundGridWebm from "@/assets/background_waves.webm";
import backgroundGridPng from "@/assets/background_waves.png";
import {useShell} from "@/contexts/ShellContext";

export const BackgroundAnimation = () => {

  const {isDark} = useShell();

  return (
    <div>
      <video
        loop
        muted
        playsInline
        autoPlay
        poster={backgroundGridPng}
        className={styles.responseVideo}
      >
        <source src={backgroundGridWebm} type="video/webm"/>
        Your browser does not support the video tag.
      </video>
      <div className={` ${styles.backgroundColor} ${isDark ? "" : styles.whiteOpacity}`}></div>
    </div>
  )
}