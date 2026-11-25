// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useRef, useState, useEffect } from "react";
import Fade from "@mui/material/Fade";
import Typography from "@mui/material/Typography";
import type { useHomeWizard } from "./useHomeWizard";
import { STRINGS } from "@/constants/strings";
import { extractProjectName } from "@/utils/workspace";
import InputsForm from "./InputsForm";
import styles from "./HomeScreen.module.css";

const HINTS = STRINGS.wizard.hints;

const HINT_INTERVAL_MS = 3000;
const HINT_EXIT_MS = 600;

type WizardProps = Pick<
  ReturnType<typeof useHomeWizard>,
  | "step"
  | "scanPaths"
  | "probe"
  | "isLoading"
  | "loadingMessage"
  | "error"
  | "promptMessage"
  | "placeholder"
  | "handleKeyDown"
  | "handlePath"
  | "handleInputs"
  | "retry"
  | "restart"
  | "data"
>;

export default function WizardView({
  step,
  scanPaths,
  probe,
  isLoading,
  loadingMessage,
  error,
  promptMessage,
  placeholder,
  handleKeyDown,
  handlePath,
  handleInputs,
  retry,
  restart,
  data,
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

  const isTextStep = step === "query" || step === "repository_url";

  const isListStep = step === "root_module_path";

  return (
    <div className={styles.center} onClick={() => inputRef.current?.focus()}>
      <Typography variant="body1" className={styles.prompt}>{promptMessage()}</Typography>

      {isLoading && (
        <Fade in timeout={500}>
          <Typography variant="h3" className={styles.loadingMsg}>
            {loadingMessage}
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
            <button className={styles.startOverBtn} onClick={restart}>
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
            defaultValue={step === "query" ? data.query : ""}
            onKeyDown={handleKeyDown}
            maxLength={500}
            placeholder={placeholder()}
            aria-label={
              step === "query"
                ? STRINGS.wizard.ariaQuery
                : STRINGS.wizard.ariaRepositoryUrl
            }
          />
        </Fade>
      )}

      {!isLoading && !error && isListStep && (
        <Fade in timeout={800}>
          <ul
            className={styles.selectContainer}
            role="listbox"
            aria-label={STRINGS.wizard.ariaRootModulePath}
          >
            {scanPaths.map((path) => (
              <Typography variant="h3" component="li" key={path} onClick={handlePathClick} role="option">
                {path}
              </Typography>
            ))}
          </ul>
        </Fade>
      )}

      {!isLoading && !error && step === "inputs" && probe && (
        <InputsForm
          probe={probe}
          project={extractProjectName(data.repositoryUrl).replace(/\.git$/, "")}
          rootModulePath={data.rootModulePath || undefined}
          onSubmit={handleInputs}
          onCancel={restart}
        />
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
