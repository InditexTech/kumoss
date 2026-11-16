// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTerraformActions } from "@/hooks/use_terraform_actions";
import { useSession } from "@/contexts/SessionContext";
import { useMode } from "@/contexts/ModeContext";
import { STRINGS } from "@/constants/strings";
import { FIXED_MODE_QUERIES, isFixedModeQuery } from "@/constants/modes";
import { useCurrentView } from "@/hooks/useCurrentView";
import { INITIAL_WIZARD_DATA, useWizardNavigation } from "@/hooks/useWizardNavigation";
import type { WizardData } from "@/hooks/useWizardNavigation";
import { useMapperResolution } from "@/hooks/useMapperResolution";
import { useWizardTerraform } from "@/hooks/useWizardTerraform";
import { nextStep } from "@/hooks/wizardFlow";
import { isMergeOnlySession } from "@/utils/session";
import { probeManifest } from "@/services/core/manifest";
import type { Session } from "@/types/ui";
import type {
  ManifestAnswers,
  ManifestProbeResponse,
  TerraformProvider,
} from "@/types/api";

const SCOPE_PATTERN = /^[a-zA-Z0-9-]+$/;

export function useHomeWizard() {
  const { session, updateSession, resetNonce } = useSession();
  const { mode } = useMode();
  const navigate = useNavigate();

  const homeView = useCurrentView() ?? "wizard";

  const navigation = useWizardNavigation();
  const mapper = useMapperResolution();
  const { handleOutcome } = useWizardTerraform();

  const terraform = useTerraformActions();

  // The root module's input probe, run when the wizard reaches "inputs".
  const [probe, setProbe] = useState<ManifestProbeResponse | null>(null);
  const [probeLoading, setProbeLoading] = useState(false);
  const [probeError, setProbeError] = useState<string | null>(null);
  // Drops the answer of a probe the user has since moved away from.
  const probeSeq = useRef(0);

  const resetProbe = useCallback(() => {
    probeSeq.current += 1;
    setProbe(null);
    setProbeLoading(false);
    setProbeError(null);
  }, []);

  useEffect(() => {
    if (terraform.state.status === "error" && homeView === "planning") {
      navigate("/home", { replace: true });
    }
  }, [terraform.state.status, homeView, navigate]);

  const start = useCallback(
    (data: WizardData) => {
      navigate("/home/planning");
      terraform.run(
        {
          repoUri: data.repositoryUrl,
          query: data.query,
          terraformProviders: data.provider as TerraformProvider,
          scopeId: data.scope,
          mode,
          rootModulePath: data.rootModulePath,
          ...(data.inputs ? { manifest: data.inputs } : {}),
        },
        handleOutcome,
      );
    },
    [navigate, terraform, mode, handleOutcome],
  );

  /**
   * Ask the backend what the root module needs. Nothing: complete the
   * wizard on the user's behalf. Something: show the form (`probe`).
   */
  const runProbe = useCallback(
    async (data: WizardData) => {
      const seq = ++probeSeq.current;
      setProbe(null);
      setProbeError(null);
      setProbeLoading(true);
      try {
        const result = await probeManifest({
          repo_uri: data.repositoryUrl,
          root_module_path: data.rootModulePath || null,
          terraform_provider: data.provider as TerraformProvider,
        });
        if (seq !== probeSeq.current) return;
        if (result.needs_input) {
          setProbe(result);
          return;
        }
        const checked = { ...data, inputsChecked: true, inputs: null };
        navigation.setData(checked);
        start(checked);
      } catch (err) {
        if (seq !== probeSeq.current) return;
        console.error("Manifest probe failed:", err);
        setProbeError(STRINGS.wizard.probeError);
      } finally {
        if (seq === probeSeq.current) setProbeLoading(false);
      }
    },
    [navigation, start],
  );

  const advance = useCallback(
    (data: WizardData) => {
      const patch: Partial<Session> = {};
      if (data.provider) patch.provider = data.provider;
      if (data.scope) patch.scope_id = data.scope;
      if (Object.keys(patch).length > 0) updateSession(patch);

      const next = nextStep(data);
      if (next === "complete") {
        start(data);
        return;
      }
      navigation.setStep(next);
      if (next === "inputs") void runProbe(data);
    },
    [navigation, updateSession, start, runProbe],
  );

  const handleInputs = useCallback(
    (answers: ManifestAnswers) => {
      advance(navigation.applyResolution({ inputsChecked: true, inputs: answers }));
    },
    [navigation, advance],
  );

  useEffect(() => {
    const fixed = FIXED_MODE_QUERIES[mode];
    const { query } = navigation.data;
    if (fixed) {
      if (query === fixed) return;
      const merged = navigation.applyResolution({ query: fixed });
      updateSession({ first_query: fixed });
      if (navigation.step === "query") advance(merged);
    } else if (isFixedModeQuery(query)) {
      navigation.applyResolution({ query: "" });
      navigation.setStep("query");
    }
  }, [mode, navigation, updateSession, advance]);

  const handleInput = useCallback(
    async (value: string) => {
      switch (navigation.step) {
        case "query": {
          if (!value.trim() || value.length > 500) return;
          updateSession({ first_query: value.trim() });
          advance(navigation.applyResolution({ query: value.trim() }));
          break;
        }

        case "repository_url": {
          if (!value.trim()) return;
          try {
            const result = await mapper.resolveAndScan(value.trim());

            if (result.paths.length === 0) {
              navigation.applyResolution({ repositoryUrl: result.repoUrl });
              updateSession({ workspace: { uri: result.repoUrl } });
              mapper.setMapperError(STRINGS.wizard.noRootModulePaths);
              break;
            }

            const path = result.paths.length === 1 ? result.paths[0] : "";
            const resolved = navigation.applyResolution({
              repositoryUrl: result.repoUrl,
              ...(path ? { rootModulePath: path } : {}),
              ...(result.provider ? { provider: result.provider } : {}),
              ...(result.scopeId ? { scope: result.scopeId } : {}),
            });
            updateSession({
              workspace: {
                uri: result.repoUrl,
                ...(path ? { root_path: path } : {}),
              },
            });
            advance(resolved);
          } catch (err) {
            console.error("Mapper resolution failed:", err);
            mapper.setMapperError(STRINGS.wizard.resolveError);
          }
          break;
        }

        case "scope": {
          const scope = value.trim().toLowerCase();
          if (!scope || !SCOPE_PATTERN.test(scope)) return;
          advance(navigation.applyResolution({ scope }));
          break;
        }

        default:
          break;
      }
    },
    [navigation, mapper, updateSession, advance],
  );

  const handlePath = useCallback(
    (path: string) => {
      updateSession({ workspace: { ...session.workspace, root_path: path } });
      advance(navigation.applyResolution({ rootModulePath: path }));
    },
    [navigation, updateSession, session.workspace, advance],
  );

  const handleProvider = useCallback(
    (provider: TerraformProvider) => {
      advance(navigation.applyResolution({ provider }));
    },
    [navigation, advance],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter" && e.currentTarget.value.trim()) {
        handleInput(e.currentTarget.value.trim());
        e.currentTarget.value = "";
      }
    },
    [handleInput],
  );

  const iterate = useCallback(
    (query: string) => {
      if (!session.uuid) return;

      navigate("/home/planning");

      terraform.run(
        {
          sessionId: session.uuid,
          query,
          mode,
        },
        handleOutcome,
      );
    },
    [session.uuid, navigate, terraform, mode, handleOutcome],
  );

  const applyAfterPr = useCallback(() => {
    if (!session.uuid) return;
    if (isMergeOnlySession(session)) return;

    navigate("/home/planning");

    terraform.run({ kind: "apply", sessionId: session.uuid }, handleOutcome);
  }, [session, navigate, terraform, handleOutcome]);

  const retry = useCallback(() => {
    if (probeError) {
      void runProbe(navigation.data);
    } else if (mapper.mapperError) {
      navigation.setStep("repository_url");
      navigation.setData((prev) => ({
        ...prev,
        repositoryUrl: "",
        provider: "",
        scope: "",
        rootModulePath: "",
        inputsChecked: false,
        inputs: null,
      }));
      mapper.resetMapper();
      resetProbe();
      terraform.reset();
    } else if (terraform.state.status === "error") {
      terraform.reset();
      navigate("/home", { replace: true });
    }
  }, [terraform, mapper, navigation, navigate, probeError, runProbe, resetProbe]);

  const restart = useCallback(() => {
    const preservedQuery = navigation.data.query;
    navigation.setStep("query");
    navigation.setData({ ...INITIAL_WIZARD_DATA, query: preservedQuery });
    mapper.resetMapper();
    resetProbe();
    terraform.reset();
    navigate("/home", { replace: true });
  }, [navigation, mapper, terraform, navigate, resetProbe]);

  const reset = useCallback(() => {
    navigation.resetNavigation();
    mapper.resetMapper();
    resetProbe();
    terraform.reset();
    navigate("/home", { replace: true });
  }, [navigation, mapper, terraform, navigate, resetProbe]);

  const seenResetNonce = useRef(resetNonce);
  useEffect(() => {
    if (seenResetNonce.current === resetNonce) return;
    seenResetNonce.current = resetNonce;
    reset();
  }, [resetNonce, reset]);

  const promptMessage = (): string => navigation.promptMessage();

  const placeholder = (): string => navigation.placeholder();

  const isLoading =
    mapper.mapperLoading ||
    probeLoading ||
    terraform.state.status === "loading";

  const loadingMessage = probeLoading
    ? STRINGS.wizard.loadingInputs
    : STRINGS.wizard.loadingRepository;

  const error =
    mapper.mapperError ??
    probeError ??
    (terraform.state.status === "error" ? terraform.state.message : null);

  return {
    step: navigation.step,
    data: navigation.data,
    homeView,
    scanPaths: mapper.scanPaths,
    probe,
    isLoading,
    loadingMessage,
    error,
    terraformState: terraform.state,
    promptMessage,
    placeholder,
    handleKeyDown,
    handleInput,
    handlePath,
    handleProvider,
    handleInputs,
    iterate,
    applyAfterPr,
    retry,
    restart,
    reset,
  } as const;
}
