// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useInitialInformation } from "@/hooks/use_initial_information";
import { useTerraformActions } from "@/hooks/use_terraform_actions";
import { useSession } from "@/contexts/SessionContext";
import { useMode } from "@/contexts/ModeContext";
import { STRINGS } from "@/constants/strings";
import { useCurrentView } from "@/hooks/useCurrentView";
import { useWizardNavigation } from "@/hooks/useWizardNavigation";
import { useMapperResolution } from "@/hooks/useMapperResolution";
import { useWizardTerraform } from "@/hooks/useWizardTerraform";
import { isDriftSession } from "@/utils/session";
import type { TerraformProvider } from "@/types/api";

const CLOUD_SCOPE_PATTERN = /^[a-zA-Z0-9-]+$/;

export function useHomeWizard() {
  const { session, updateSession, resetNonce } = useSession();
  const { mode } = useMode();
  const navigate = useNavigate();

  const homeView = useCurrentView() ?? "wizard";

  const navigation = useWizardNavigation();
  const mapper = useMapperResolution();
  const { handleOutcome } = useWizardTerraform();

  const auth = useInitialInformation();
  const terraform = useTerraformActions();

  const hasTriggeredTerraform = useRef(false);

  // When authorization succeeds, kick off the terraform action
  useEffect(() => {
    if (auth.state.status === "success" && !hasTriggeredTerraform.current) {
      hasTriggeredTerraform.current = true;

      navigate("/home/planning");

      terraform.run(
        {
          repoUri: navigation.data.repositoryUrl,
          query: navigation.data.query,
          terraformProviders: navigation.data.provider as TerraformProvider,
          scopeId: navigation.data.cloudScope,
          mode,
          iacPath: navigation.data.iacPath,
        },
        handleOutcome,
      );
    }
  }, [auth.state.status, navigation.data, mode, terraform, navigate, handleOutcome]);

  useEffect(() => {
    if (terraform.state.status === "error" && homeView === "planning") {
      navigate("/home", { replace: true });
    }
  }, [terraform.state.status, homeView, navigate]);

  const handleInput = useCallback(
    async (value: string) => {
      switch (navigation.step) {
        case "query": {
          if (!value.trim() || value.length > 500) return;
          navigation.setData((prev) => ({ ...prev, query: value.trim() }));
          updateSession({ first_query: value.trim() });
          navigation.setStep("repository_url");
          break;
        }

        case "repository_url": {
          if (!value.trim()) return;
          try {
            const result = await mapper.resolveAndScan(value.trim());
            navigation.setData((prev) => ({
              ...prev,
              repositoryUrl: result.repoUrl,
            }));
            updateSession({ workspace: { uri: result.repoUrl } });

            if (result.paths.length === 0) {
              mapper.setMapperError(STRINGS.wizard.noIacPaths);
            } else if (result.paths.length === 1) {
              const path = result.paths[0];
              navigation.setData((prev) => ({ ...prev, iacPath: path }));
              updateSession({
                workspace: { uri: result.repoUrl, root_path: path },
              });
              navigation.setStep("provider");
            } else {
              navigation.setStep("iac_path");
            }
          } catch (err) {
            console.error("Mapper resolution failed:", err);
            mapper.setMapperError(STRINGS.wizard.resolveError);
          }
          break;
        }

        case "cloud_scope": {
          const scope = value.trim().toLowerCase();
          if (!scope || !CLOUD_SCOPE_PATTERN.test(scope)) return;
          navigation.setData((prev) => ({ ...prev, cloudScope: scope }));
          updateSession({ scope_id: scope });

          auth.run({
            repositoryUrl: navigation.data.repositoryUrl,
            query: navigation.data.query,
            cloud: navigation.data.provider,
            environment: navigation.data.iacPath,
          });
          break;
        }

        default:
          break;
      }
    },
    [navigation, mapper, updateSession, auth],
  );

  const handlePath = useCallback(
    (path: string) => {
      navigation.setData((prev) => ({ ...prev, iacPath: path }));
      updateSession({ workspace: { ...session.workspace, root_path: path } });
      navigation.setStep("provider");
    },
    [navigation, updateSession, session.workspace],
  );

  const handleProvider = useCallback(
    (provider: TerraformProvider) => {
      navigation.setData((prev) => ({ ...prev, provider }));
      updateSession({ provider });
      navigation.setStep("cloud_scope");
    },
    [navigation, updateSession],
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
    // Drift is remediated by merging the PR; applying afterwards would re-run
    // work the merge just completed. ResultsRoute already declines to call
    // this, but the callback is reachable through the outlet context.
    if (isDriftSession(session)) return;

    navigate("/home/planning");

    terraform.run(
      {
        sessionId: session.uuid,
        query: "",
        mode: "import" as const,
      },
      handleOutcome,
    );
  }, [session, navigate, terraform, handleOutcome]);

  const retry = useCallback(() => {
    if (mapper.mapperError) {
      navigation.setStep("repository_url");
      navigation.setData((prev) => ({ ...prev, repositoryUrl: "", provider: "", cloudScope: "", iacPath: "" }));
      mapper.resetMapper();
      hasTriggeredTerraform.current = false;
      auth.reset();
      terraform.reset();
    } else if (auth.state.status === "error") {
      navigation.setStep("cloud_scope");
      navigation.setData((prev) => ({ ...prev, cloudScope: "" }));
      hasTriggeredTerraform.current = false;
      auth.reset();
      terraform.reset();
      navigate("/home", { replace: true });
    } else if (terraform.state.status === "error") {
      hasTriggeredTerraform.current = false;
      terraform.reset();
      navigate("/home", { replace: true });
    }
  }, [auth, terraform, mapper, navigation, navigate]);

  const reset = useCallback(() => {
    navigation.resetNavigation();
    mapper.resetMapper();
    hasTriggeredTerraform.current = false;
    auth.reset();
    terraform.reset();
    navigate("/home", { replace: true });
  }, [navigation, mapper, auth, terraform, navigate]);

  // A clear requested from outside the wizard: the header logo calls
  // `resetSession()`, which bumps `resetNonce`. The ref is seeded with the
  // mount-time value so a fresh mount — a deep link into
  // /home/results/:id, say — is not mistaken for a reset request.
  const seenResetNonce = useRef(resetNonce);
  useEffect(() => {
    if (seenResetNonce.current === resetNonce) return;
    seenResetNonce.current = resetNonce;
    reset();
  }, [resetNonce, reset]);

  const promptMessage = (): string =>
    navigation.promptMessage(auth.state.status);

  const placeholder = (): string => navigation.placeholder();

  const isLoading =
    mapper.mapperLoading ||
    auth.state.status === "loading" ||
    terraform.state.status === "loading";

  const error =
    mapper.mapperError ??
    (auth.state.status === "error" ? auth.state.message : null) ??
    (terraform.state.status === "error" ? terraform.state.message : null);

  return {
    step: navigation.step,
    data: navigation.data,
    homeView,
    scanPaths: mapper.scanPaths,
    isLoading,
    error,
    authState: auth.state,
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
    reset,
  } as const;
}
