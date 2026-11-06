// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useTerraformActions } from "@/hooks/use_terraform_actions";
import { useSession } from "@/contexts/SessionContext";
import { useMode } from "@/contexts/ModeContext";
import { STRINGS } from "@/constants/strings";
import { FIXED_MODE_QUERIES, isFixedModeQuery } from "@/constants/modes";
import { useCurrentView } from "@/hooks/useCurrentView";
import { useWizardNavigation } from "@/hooks/useWizardNavigation";
import type { WizardData } from "@/hooks/useWizardNavigation";
import { useMapperResolution } from "@/hooks/useMapperResolution";
import { useWizardTerraform } from "@/hooks/useWizardTerraform";
import { nextStep } from "@/hooks/wizardFlow";
import { isMergeOnlySession } from "@/utils/session";
import type { Session } from "@/types/ui";
import type { TerraformProvider } from "@/types/api";

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

  useEffect(() => {
    if (terraform.state.status === "error" && homeView === "planning") {
      navigate("/home", { replace: true });
    }
  }, [terraform.state.status, homeView, navigate]);

  const advance = useCallback(
    (data: WizardData) => {
      const patch: Partial<Session> = {};
      if (data.provider) patch.provider = data.provider;
      if (data.scope) patch.scope_id = data.scope;
      if (Object.keys(patch).length > 0) updateSession(patch);

      const next = nextStep(data);
      if (next === "complete") {
        navigate("/home/planning");
        terraform.run(
          {
            repoUri: data.repositoryUrl,
            query: data.query,
            terraformProviders: data.provider as TerraformProvider,
            scopeId: data.scope,
            mode,
            iacPath: data.iacPath,
          },
          handleOutcome,
        );
        return;
      }
      navigation.setStep(next);
    },
    [navigation, updateSession, terraform, navigate, mode, handleOutcome],
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
              mapper.setMapperError(STRINGS.wizard.noIacPaths);
              break;
            }

            const path = result.paths.length === 1 ? result.paths[0] : "";
            const resolved = navigation.applyResolution({
              repositoryUrl: result.repoUrl,
              ...(path ? { iacPath: path } : {}),
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
      advance(navigation.applyResolution({ iacPath: path }));
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
    if (mapper.mapperError) {
      navigation.setStep("repository_url");
      navigation.setData((prev) => ({ ...prev, repositoryUrl: "", provider: "", scope: "", iacPath: "" }));
      mapper.resetMapper();
      terraform.reset();
    } else if (terraform.state.status === "error") {
      terraform.reset();
      navigate("/home", { replace: true });
    }
  }, [terraform, mapper, navigation, navigate]);

  const restart = useCallback(() => {
    const preservedQuery = navigation.data.query;
    navigation.setStep("query");
    navigation.setData({
      query: preservedQuery,
      repositoryUrl: "",
      provider: "",
      scope: "",
      iacPath: "",
    });
    mapper.resetMapper();
    terraform.reset();
    navigate("/home", { replace: true });
  }, [navigation, mapper, terraform, navigate]);

  const reset = useCallback(() => {
    navigation.resetNavigation();
    mapper.resetMapper();
    terraform.reset();
    navigate("/home", { replace: true });
  }, [navigation, mapper, terraform, navigate]);

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
    terraform.state.status === "loading";

  const error =
    mapper.mapperError ??
    (terraform.state.status === "error" ? terraform.state.message : null);

  return {
    step: navigation.step,
    data: navigation.data,
    homeView,
    scanPaths: mapper.scanPaths,
    isLoading,
    error,
    terraformState: terraform.state,
    promptMessage,
    placeholder,
    handleKeyDown,
    handleInput,
    handlePath,
    handleProvider,
    iterate,
    applyAfterPr,
    retry,
    restart,
    reset,
  } as const;
}
