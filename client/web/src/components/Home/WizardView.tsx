// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useRef, useState, useEffect } from "react";
import Fade from "@mui/material/Fade";
import Typography from "@mui/material/Typography";
import type { useHomeWizard } from "./useHomeWizard";
import { STRINGS } from "@/constants/strings";
import { providerLabel } from "@/constants/providers";
import { TERRAFORM_PROVIDERS } from "@/types/api";
import { ProviderIcon } from "@/components/ui";
import styles from "./HomeScreen.module.css";

const HINTS = STRINGS.wizard.hints;

const HINT_INTERVAL_MS = 3000;
const HINT_EXIT_MS = 600;

type WizardProps = Pick<
  ReturnType<typeof useHomeWizard>,
  | "step"
  | "scanPaths"
  | "isLoading"
  | "error"
  | "promptMessage"
  | "placeholder"
  | "handleKeyDown"
  | "handlePath"
  | "handleProvider"
  | "retry"
  | "reset"
>;

export default function WizardView({
  step,
  scanPaths,
  isLoading,
  error,
  promptMessage,
  placeholder,
  handleKeyDown,
  handlePath,
  handleProvider,
  retry,
  reset,
}: WizardProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [hintIndex, setHintIndex] = useState(0);
  const [hintPhase, setHintPhase] = useState<"in" | "out">("in");

  useEffect(() => {
    if (step !== "query") return;
    const interval = setInterval(() => {
      setHintPhase("out");
      setTimeout(() => {
        setHintIndex((i) => (i + 1) % HINTS.length);
        setHintPhase("in");
      }, HINT_EXIT_MS);
    }, HINT_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [step]);

  const handlePathClick = useCallback(
    (e: React.MouseEvent<HTMLLIElement>) => {
      handlePath(e.currentTarget.innerText);
    },
    [handlePath],
  );

  const isTextStep =
    step === "query" || step === "repository_url" || step === "cloud_scope";

  const isListStep = step === "iac_path";

  const isProviderStep = step === "provider";

  return (
    <div className={styles.center} onClick={() => inputRef.current?.focus()}>
      <Typography variant="body1" className={styles.prompt}>{promptMessage()}</Typography>

      {isLoading && (
        <Fade in timeout={500}>
          <Typography variant="h3" className={styles.loadingMsg}>
            {step === "repository_url"
              ? STRINGS.wizard.loadingRepository
              : STRINGS.wizard.loadingPermissions}
          </Typography>
        </Fade>
      )}

      {error && (
        <Fade in timeout={500}>
          <div style={{ textAlign: "center" }}>
            <Typography variant="body1" className={styles.errorMsg}>{error}</Typography>
            <button className={styles.retryBtn} onClick={retry}>
              {STRINGS.wizard.tryAgain}
            </button>
            <button className={styles.startOverBtn} onClick={reset}>
              {STRINGS.wizard.startOver}
            </button>
          </div>
        </Fade>
      )}

      {!isLoading && !error && isTextStep && (
        <Fade in timeout={500} key={step}>
          <input
            ref={inputRef}
            type="text"
            id="wizard-input"
            name="wizard-input"
            autoComplete="off"
            autoFocus
            className={styles.input}
            onKeyDown={handleKeyDown}
            maxLength={step === "cloud_scope" ? 64 : 500}
            placeholder={placeholder()}
            aria-label={
              step === "query"
                ? STRINGS.wizard.ariaQuery
                : step === "repository_url"
                  ? STRINGS.wizard.ariaRepositoryUrl
                  : STRINGS.wizard.ariaCloudScope
            }
          />
        </Fade>
      )}

      {!isLoading && !error && isListStep && (
        <Fade in timeout={800}>
          <ul
            className={styles.selectContainer}
            role="listbox"
            aria-label={STRINGS.wizard.ariaIacPath}
          >
            {scanPaths.map((path) => (
              <Typography variant="h3" component="li" key={path} onClick={handlePathClick} role="option">
                {path}
              </Typography>
            ))}
          </ul>
        </Fade>
      )}

      {!isLoading && !error && isProviderStep && (
        <Fade in timeout={800}>
          <ul
            className={styles.selectContainer}
            role="listbox"
            aria-label={STRINGS.wizard.ariaProvider}
          >
            {TERRAFORM_PROVIDERS.map((provider) => (
              <Typography
                variant="h3"
                component="li"
                key={provider}
                onClick={() => handleProvider(provider)}
                role="option"
                className={styles.providerOption}
              >
                <ProviderIcon provider={provider} className={styles.providerIcon} />
                {providerLabel(provider)}
              </Typography>
            ))}
          </ul>
        </Fade>
      )}

      {step === "query" && !isLoading && !error && (
        <div className={styles.hintWrapper}>
          <Typography
            variant="subtitle2"
            component="span"
            key={hintIndex}
            className={`${styles.hint} ${hintPhase === "in" ? styles.hintIn : styles.hintOut}`}
          >
            {HINTS[hintIndex]}
          </Typography>
        </div>
      )}
    </div>
  );
}
