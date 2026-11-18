// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import ButtonBase from "@mui/material/ButtonBase";
import CloseIcon from "@mui/icons-material/Close";
import LockOutlinedIcon from "@mui/icons-material/LockOutlined";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import { STRINGS } from "@/constants/strings";
import { scopeLabel, scopePlaceholder } from "@/constants/providers";
import type {
  ManifestAnswers,
  ManifestMissingScope,
  ManifestProbeResponse,
  ManifestVariable,
} from "@/types/api";
import {
  buildAnswers,
  exampleFor,
  hasStructure,
  initialFormState,
  inputKind,
  isAnswered,
  isSecret,
  missingScopes,
  scopeErrorKey,
  scopeValue,
  setByVarFiles,
  toggleVarFile,
  typeLabel,
} from "@/utils/manifestInputs";
import type { InputsFormState } from "@/utils/manifestInputs";
import styles from "./InputsForm.module.css";

const S = STRINGS.wizard.inputs;

interface InputsFormProps {
  probe: ManifestProbeResponse;
  /** Repository and root module the answers are for, shown in the title. */
  project?: string;
  rootModulePath?: string;
  onSubmit: (answers: ManifestAnswers) => void;
  onCancel?: () => void;
}

/**
 * Full-viewport dialog asking for what the manifest probe reported missing:
 * a scope id per provider that has none, a value per uncovered variable,
 * whether to keep it as a secret, and which optional var files to pass.
 */
export default function InputsForm({
  probe,
  project,
  rootModulePath,
  onSubmit,
  onCancel,
}: InputsFormProps) {
  const [state, setState] = useState<InputsFormState>(() => initialFormState(probe));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const titleId = useId();
  const formRef = useRef<HTMLFormElement>(null);

  const scopes = missingScopes(probe);
  const setBy = useMemo(() => setByVarFiles(probe, state), [probe, state]);
  const answered =
    scopes.filter((s) => scopeValue(s.provider, state) !== null).length +
    probe.missing_variables.filter((v) => isAnswered(v, state, setBy)).length;
  const total = scopes.length + probe.missing_variables.length;
  // A scopes-only probe has no values to list.
  const showValues = probe.missing_variables.length > 0 || scopes.length === 0;

  const clearError = useCallback((name: string) => {
    setErrors((prev) => {
      if (!(name in prev)) return prev;
      const rest = { ...prev };
      delete rest[name];
      return rest;
    });
  }, []);

  const setValue = useCallback(
    (name: string, value: string | boolean) => {
      setState((prev) => ({ ...prev, values: { ...prev.values, [name]: value } }));
      clearError(name);
    },
    [clearError],
  );

  const setScope = useCallback(
    (provider: string, value: string) => {
      setState((prev) => ({ ...prev, scopes: { ...prev.scopes, [provider]: value } }));
      clearError(scopeErrorKey(provider));
    },
    [clearError],
  );

  const setSecret = useCallback((name: string, secret: boolean) => {
    setState((prev) => ({ ...prev, secret: { ...prev.secret, [name]: secret } }));
  }, []);

  const pickVarFile = useCallback((path: string) => {
    setState((prev) => ({ ...prev, varFiles: toggleVarFile(prev.varFiles, path) }));
  }, []);

  const submit = useCallback(() => {
    const result = buildAnswers(probe, state);
    if (result.ok) {
      onSubmit(result.answers);
      return;
    }
    setErrors(result.errors);
    // Focus the first invalid field, in the order they are shown.
    const firstKey = [
      ...missingScopes(probe).map((s) => scopeErrorKey(s.provider)),
      ...probe.missing_variables.map((v) => v.name),
    ].find((key) => key in result.errors);
    if (firstKey) document.getElementById(fieldId(titleId, firstKey))?.focus();
  }, [probe, state, onSubmit, titleId]);

  const onFormSubmit = useCallback(
    (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      submit();
    },
    [submit],
  );

  // Esc cancels; Ctrl/Cmd + Enter submits from anywhere in the dialog.
  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape" && onCancel) {
        e.preventDefault();
        onCancel();
      } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        submit();
      }
    },
    [onCancel, submit],
  );

  // Start on the first field; keep the page behind from scrolling.
  useEffect(() => {
    formRef.current?.querySelector<HTMLElement>("input:not([type=checkbox]), textarea")?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  return createPortal(
    <div
      className={styles.overlay}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onKeyDown={onKeyDown}
    >
      <form ref={formRef} className={styles.shell} onSubmit={onFormSubmit} noValidate>
        <header className={styles.topBar}>
          <div className={styles.heading}>
            <span className={styles.eyebrow}>{S.eyebrow}</span>
            <h2 id={titleId} className={styles.title}>
              {project ?? STRINGS.wizard.promptInputs}
              {rootModulePath && (
                <>
                  <span className={styles.titleSep}>/</span>
                  <span className={styles.titleModule}>{rootModulePath}</span>
                </>
              )}
            </h2>
            <p className={styles.intro}>
              {probe.status === "drifted" ? S.driftedIntro : S.intro}
            </p>
          </div>
          {onCancel && (
            <ButtonBase className={styles.close} onClick={onCancel} aria-label={S.close}>
              <CloseIcon fontSize="small" />
            </ButtonBase>
          )}
        </header>

        <div className={styles.body}>
          <div className={styles.main}>
            {scopes.length > 0 && (
              <section className={styles.group} aria-label={S.scopesHeading}>
                <h3 className={styles.sectionTitle}>
                  {S.scopesHeading}
                  <span className={styles.count}>{scopes.length}</span>
                </h3>
                <p className={styles.groupHelp}>{S.scopesHelp}</p>
                {scopes.map((scope) => (
                  <ScopeField
                    key={scope.provider}
                    id={fieldId(titleId, scopeErrorKey(scope.provider))}
                    scope={scope}
                    value={state.scopes[scope.provider] ?? ""}
                    error={errors[scopeErrorKey(scope.provider)]}
                    onValue={setScope}
                  />
                ))}
              </section>
            )}

            {showValues && (
              <section className={styles.group} aria-label={S.valuesHeading}>
                <h3 className={styles.sectionTitle}>
                  {S.valuesHeading}
                  <span className={styles.count}>{probe.missing_variables.length}</span>
                </h3>
                {probe.missing_variables.map((variable) => (
                  <VariableField
                    key={variable.name}
                    id={fieldId(titleId, variable.name)}
                    variable={variable}
                    setBy={setBy.get(variable.name)}
                    value={state.values[variable.name] ?? ""}
                    secret={isSecret(variable, state)}
                    error={errors[variable.name]}
                    onValue={setValue}
                    onSecret={setSecret}
                  />
                ))}
              </section>
            )}
          </div>

          <aside className={styles.aside}>
            {(probe.selectable_var_files.length > 0 || probe.missing_var_files.length > 0) && (
              <section className={styles.panel} aria-label={S.varFilesHeading}>
                <h3 className={styles.sectionTitle}>{S.varFilesHeading}</h3>
                <p className={styles.panelHelp}>{S.varFilesHelp}</p>
                {probe.missing_var_files.length > 0 && (
                  <p className={styles.warning} role="alert">
                    <WarningAmberIcon fontSize="inherit" />
                    <span>
                      {S.missingVarFiles} {probe.missing_var_files.join(", ")}
                    </span>
                  </p>
                )}
                <ul className={styles.fileList}>
                  {probe.selectable_var_files.map((file) => {
                    const position = state.varFiles.indexOf(file.path);
                    const picked = position >= 0;
                    const asked = file.sets.filter((name) =>
                      probe.missing_variables.some((v) => v.name === name),
                    );
                    return (
                      <li key={file.path}>
                        <label className={`${styles.file} ${picked ? styles.filePicked : ""}`}>
                          <input
                            type="checkbox"
                            className={styles.visuallyHidden}
                            checked={picked}
                            onChange={() => pickVarFile(file.path)}
                          />
                          <span className={styles.fileOrder} aria-hidden="true">
                            {picked ? position + 1 : <DescriptionOutlinedIcon fontSize="inherit" />}
                          </span>
                          <span className={styles.fileText}>
                            <span className={styles.filePath}>{file.path}</span>
                            <span className={styles.fileSets}>
                              {asked.length > 0
                                ? `${S.varFileSets} ${asked.join(", ")}`
                                : S.varFileSetsNothing}
                            </span>
                          </span>
                        </label>
                      </li>
                    );
                  })}
                </ul>
              </section>
            )}

            <section className={styles.panel} aria-label={S.storageHeading}>
              <h3 className={styles.sectionTitle}>{S.storageHeading}</h3>
              <p className={styles.panelHelp}>{S.storagePlain}</p>
              <p className={styles.panelHelp}>
                <LockOutlinedIcon fontSize="inherit" className={styles.inlineIcon} />
                {S.storageSecret}
              </p>
            </section>
          </aside>
        </div>

        <footer className={styles.bottomBar}>
          <div className={styles.progress} aria-live="polite">
            <span className={styles.progressTrack}>
              <span
                className={styles.progressFill}
                style={{ width: `${total ? (answered / total) * 100 : 100}%` }}
              />
            </span>
            <span>
              {S.progress.replace("{done}", String(answered)).replace("{total}", String(total))}
            </span>
          </div>
          <div className={styles.actions}>
            {onCancel && (
              <button type="button" className={styles.secondary} onClick={onCancel}>
                {S.cancel}
              </button>
            )}
            <button type="submit" className={styles.primary}>
              {S.submit}
              <kbd className={styles.kbd}>{S.shortcut}</kbd>
            </button>
          </div>
        </footer>
      </form>
    </div>,
    document.body,
  );
}

function fieldId(base: string, name: string): string {
  return `${base}-input-${name}`;
}

interface ScopeFieldProps {
  id: string;
  scope: ManifestMissingScope;
  value: string;
  error: string | undefined;
  onValue: (provider: string, value: string) => void;
}

/** A required, single-line scope id for one provider. */
function ScopeField({ id, scope, value, error, onValue }: ScopeFieldProps) {
  const invalid = error !== undefined;
  const errorId = `${id}-error`;
  const sourceId = `${id}-source`;
  const describedBy = [scope.source ? sourceId : "", invalid ? errorId : ""]
    .filter(Boolean)
    .join(" ") || undefined;

  return (
    <div className={`${styles.field} ${invalid ? styles.fieldInvalid : ""}`}>
      <div className={styles.fieldHeader}>
        <label htmlFor={id} className={styles.fieldName}>
          {scope.provider}
        </label>
        <span className={styles.scopePill}>{scopeLabel(scope.provider)}</span>
      </div>

      {scope.source && (
        <p id={sourceId} className={styles.description}>
          <code className={styles.source}>{scope.source}</code>
        </p>
      )}

      <input
        id={id}
        className={styles.control}
        type="text"
        autoComplete="off"
        spellCheck={false}
        required
        value={value}
        placeholder={scopePlaceholder(scope.provider)}
        aria-invalid={invalid}
        aria-describedby={describedBy}
        onChange={(e) => onValue(scope.provider, e.target.value)}
      />

      {invalid && (
        <div className={styles.fieldFooter}>
          <span id={errorId} className={styles.error} role="alert">
            {error}
          </span>
        </div>
      )}
    </div>
  );
}

interface VariableFieldProps {
  id: string;
  variable: ManifestVariable;
  /** The picked var file that already sets this variable, if any. */
  setBy: string | undefined;
  value: string | boolean;
  secret: boolean;
  error: string | undefined;
  onValue: (name: string, value: string | boolean) => void;
  onSecret: (name: string, secret: boolean) => void;
}

function VariableField({
  id,
  variable,
  setBy,
  value,
  secret,
  error,
  onValue,
  onSecret,
}: VariableFieldProps) {
  const kind = inputKind(variable.type);
  const isJson = kind === "list" || kind === "map" || kind === "any";
  const invalid = error !== undefined;
  const errorId = `${id}-error`;
  const descriptionId = `${id}-description`;
  const describedBy = [variable.description ? descriptionId : "", invalid ? errorId : ""]
    .filter(Boolean)
    .join(" ") || undefined;
  const placeholder = setBy
    ? S.setByVarFilePlaceholder.replace("{file}", setBy)
    : isJson
      ? (exampleFor(variable.type) ?? "")
      : "";

  return (
    <div
      className={`${styles.field} ${invalid ? styles.fieldInvalid : ""} ${setBy ? styles.fieldCovered : ""}`}
    >
      <div className={styles.fieldHeader}>
        <label htmlFor={id} className={styles.fieldName}>
          {variable.name}
        </label>
        <span className={styles.typePill} title={variable.type ?? S.untyped}>
          {typeLabel(variable.type)}
        </span>
        {variable.sensitive && (
          <span className={styles.sensitivePill}>
            <LockOutlinedIcon fontSize="inherit" />
            {S.sensitiveBadge}
          </span>
        )}
        {setBy && (
          <span className={styles.coveredPill}>
            <DescriptionOutlinedIcon fontSize="inherit" />
            {S.setByVarFile.replace("{file}", setBy)}
          </span>
        )}
        <label
          className={`${styles.secretToggle} ${variable.sensitive ? styles.secretLocked : ""}`}
          title={variable.sensitive ? S.secretLocked : S.secretHelp}
        >
          <input
            type="checkbox"
            role="switch"
            className={styles.switchInput}
            checked={secret}
            disabled={variable.sensitive}
            onChange={(e) => onSecret(variable.name, e.target.checked)}
            aria-label={variable.sensitive ? S.secretLocked : `${S.secretLabel}: ${variable.name}`}
          />
          <span className={styles.switch} aria-hidden="true" />
          <span>{S.secretLabel}</span>
        </label>
      </div>

      {variable.description && (
        <p id={descriptionId} className={styles.description}>
          {variable.description}
        </p>
      )}
      {hasStructure(variable.type) && kind !== "list" && (
        <code className={styles.typeFull}>{variable.type}</code>
      )}

      {kind === "bool" ? (
        <label className={styles.boolControl}>
          <input
            id={id}
            type="checkbox"
            role="switch"
            className={styles.switchInput}
            checked={value === true}
            aria-describedby={describedBy}
            onChange={(e) => onValue(variable.name, e.target.checked)}
          />
          <span className={styles.switch} aria-hidden="true" />
          <span className={styles.boolValue}>
            {value === true
              ? S.boolOn
              : value === "" && setBy
                ? S.boolFromVarFile.replace("{file}", setBy)
                : S.boolOff}
          </span>
        </label>
      ) : isJson ? (
        <textarea
          id={id}
          className={`${styles.control} ${styles.json}`}
          value={String(value)}
          rows={kind === "map" && hasStructure(variable.type) ? 4 : 2}
          spellCheck={false}
          placeholder={placeholder}
          aria-invalid={invalid}
          aria-describedby={describedBy}
          onChange={(e) => onValue(variable.name, e.target.value)}
        />
      ) : (
        <input
          id={id}
          className={styles.control}
          type={secret && kind === "string" ? "password" : "text"}
          inputMode={kind === "number" ? "decimal" : undefined}
          autoComplete="off"
          spellCheck={false}
          value={String(value)}
          placeholder={placeholder}
          aria-invalid={invalid}
          aria-describedby={describedBy}
          onChange={(e) => onValue(variable.name, e.target.value)}
        />
      )}

      {(invalid || isJson) && (
        <div className={styles.fieldFooter}>
          {invalid ? (
            <span id={errorId} className={styles.error} role="alert">
              {error}
            </span>
          ) : (
            <span className={styles.hint}>{kind === "any" ? S.anyHelp : S.jsonHelp}</span>
          )}
        </div>
      )}
    </div>
  );
}
