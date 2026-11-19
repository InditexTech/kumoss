// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

export const STRINGS = {
  common: {
    loading: "Loading...",
    confirmTitle: "Confirmation",
    confirmMessage:
      "Confirm you read and understood the report and the proposed infrastructure changes. Any doubt please ask for a review",
  },

  login: {
    signIn: "Sign In",
    sessionExpired: "Your session has expired. Please sign in again.",
    generateTitle: "Generate Infrastructure",
    generateDescription:
      "Describe what you need in plain language and get production-ready Terraform code.",
    detectDriftTitle: "Detect Drift",
    detectDriftDescription:
      "Compare your live infrastructure against your Terraform state and auto-remediate differences.",
    importTitle: "Import Resources",
    importDescription:
      "Bring existing cloud resources under Terraform management with a single command.",
  },

  chat: {
    followUpPlaceholder: "Ask a follow-up question...",
    followUpDisabledPlaceholder: "This session failed and can't be resumed",
  },

  planning: {
    preparingWorkspace: "Preparing your workspace…",
    resultsLoadError: "Completed, but results could not be loaded",
  },

  assistant: {
    answerPlaceholder: "Answer here",
    modifyPrompt: "Do you want to add or modify something?",
    modifyPlaceholder: "I also want a Key Vault.",
    viewPr: "View Pull Request",
    approvePrAndApply: "Approve PR and Apply",
    backToReport: "Back to Report",
    deletionDetectedMessage:
      "The plan includes resources that will be deleted. The support team has been notified for review.",
    contactTeam: "Contact Team",
  },

  pr: {
    ready: "Here is your Pull Request.",
    applyPrompt:
      "Do you want to apply the changes and create the infrastructure?",
    conflictNotice: "I created your PR, but you have one or more conflicts.",
    conflictAction:
      "Solve them, and notify the Data DevOps team to apply the infrastructure.",
    continuePr: "Continue with Pull Request",
    createPr: "Create Pull Request",
    showReport: "Show Report",
    showCode: "Show Code",
    confirmApply: "Confirm and Apply",
    requestReview: "Request Review",
    // Drift/import wording: merging the PR ends the flow (it *is* the
    // remediation; an import is already in state), so nothing is applied
    // afterwards and the labels must not promise it.
    mergePrompt: "",
    approveAndMerge: "Approve and Merge PR",
    confirmMerge: "Confirm and Merge",
    merging: "Merging…",
    mergeSuccess:
      "Pull Request merged. Your infrastructure is being updated to its declared state.",
    importMergeSuccess:
      "Pull Request merged. The imported resources are now managed from your repository.",
    blockedTitle: "Deployment Blocked",
    blockedMessage:
      "A specialist has been notified and will review this deployment before it can proceed.",
    blockedWhy: "Why",
    highImpactReason: "High impact",
    complianceReason: "Compliance",
    showAllFindings: "Show all findings",
    hideFindings: "Hide findings",
    checkAgain: "Check again",
    checkingLock: "Checking…",
    stillBlocked: "The deployment is still blocked.",
    blockedOnMerge:
      "This deployment was blocked before the merge. A specialist will review it.",
  },

  applyResults: {
    success: "Apply finished successfully",
    partial: "Apply partially completed",
    failure: "Apply failed",
    taskLabel: "Task:",
    taskValue: "Terraform Apply",
    completedLabel: "Completed:",
    errorMessage:
      "Infrastructure application error. The Kumoss team can help you resolve it.",
    viewResources: "View Resources",
  },

  support: {
    buttonText: "CONTACT SUPPORT",
    creatingNotification: "Sending support request...",
    creatingButton: "SENDING SUPPORT REQUEST",
    groupCreated: "Support request sent. The team has been notified.",
    sendFailed: "Support request could not be sent.",
    openLink: "Click here to open Kumoss",
    noEmailError: "Error: No user email found. Please login again.",
    tooltip:
      "Contact the Kumoss team - they will help you to: \
- See the terraform plan \
- Analyze the terraform report \
- Help you to deploy your infraestructure",
  },

  supportModal: {
    title: "Support",
    description: "How can we help you?",
    placeholder: "Describe your question or issue...",
    send: "Send",
    sending: "Sending...",
    emptyError: "Please enter a question",
    maxLengthError: "Question must be 500 characters or less",
    htmlError: "Please remove any HTML or code formatting",
    success: "Your question has been sent successfully",
    failure: "Your question could not be sent.",
  },

  wizard: {
    hints: [
      "Configure network rules",
      "Deploy a PostgreSQL database on Azure",
      "Add a load balancer to my GCP project",
      "Update storage account replication to GRS",
      "Create a virtual network with three subnets",
      "Set up a Kubernetes cluster with autoscaling",
      "Enable diagnostic logging on all resources",
    ],
    loadingRepository: "Scanning repository...",
    tryAgain: "Try again",
    startOver: "Start over",
    ariaQuery: "Describe your infrastructure request",
    ariaRepositoryUrl: "Repository URL",
    ariaRootModulePath: "Root module path",
    promptQuery: "What do you need?",
    promptRepository: "What is the repository URL?",
    promptRootModulePath: "Which root module?",
    placeholderQuery: "Type your request...",
    placeholderRepository: "https://dev.azure.com/org/project/_git/repo",
    /**
     * Scope id in each provider's own jargon. Keys are Terraform provider
     * type names: only these providers take a scope id.
     */
    scopeByProvider: {
      azurerm: { label: "Subscription ID", placeholder: "00000000-0000-0000-0000-000000000000" },
      google: { label: "Project ID", placeholder: "my-gcp-project-id" },
      aws: { label: "Account ID", placeholder: "123456789012" },
      oci: { label: "Compartment OCID", placeholder: "ocid1.compartment.oc1..aaaa…" },
    } as Record<string, { label: string; placeholder: string } | undefined>,
    scopeFallbackLabel: "Scope",
    scanError: "Could not scan the repository for root modules. Please try again.",
    noRootModulePaths:
      "No root modules found in this repository. Please check the repository and try again.",
    promptInputs: "This root module needs a few values",
    loadingInputs: "Checking what the root module needs...",
    probeError: "Could not read the root module's Kumoss manifest. Please try again.",
    inputs: {
      eyebrow: "Configure Kumoss manifest",
      intro:
        "Asked once. Answers are saved to the Kumoss manifest and reused by every later session.",
      driftedIntro:
        "The root module changed since its Kumoss manifest was saved. Only what the change needs is asked.",
      scopesHeading: "Scopes",
      scopesHelp: "Where each provider works. Saved to the Kumoss manifest.",
      valuesHeading: "Values",
      varFilesHeading: "Variable files",
      varFilesHelp: "Passed as -var-file in the order picked. Your values apply on top.",
      varFileSets: "Sets",
      varFileSetsNothing: "Sets no asked variable",
      missingVarFiles: "No longer in the repository:",
      setByVarFile: "Set by {file}",
      setByVarFilePlaceholder: "Leave empty to use {file}",
      boolFromVarFile: "From {file} unless switched",
      secretLabel: "Secret",
      secretHelp: "Kept out of the repository: only the name is committed.",
      secretLocked: "Declared sensitive: always stored as a secret",
      sensitiveBadge: "sensitive",
      storageHeading: "Where answers go",
      storagePlain: "Plain values go in the Kumoss manifest (kumoss.yaml), committed in the root module.",
      storageSecret: "Secrets are stored by Kumoss; the Kumoss manifest only names them.",
      jsonHelp: "JSON",
      anyHelp: "JSON, or plain text",
      untyped: "any",
      boolOn: "true",
      boolOff: "false",
      required: "A value is required",
      invalidJson: "Enter valid JSON",
      invalidNumber: "Enter a number",
      wrongShape: { list: "Enter a JSON list", map: "Enter a JSON object" },
      progress: "{done} of {total} answered",
      cancel: "Cancel",
      close: "Close",
      submit: "Start session",
      shortcut: "Ctrl + Enter",
    },
  },

  sessions: {
    pageTitle: "Sessions",
    searchPlaceholder: "Search User or Project",
    noSessions: "No sessions found",

    /** Timeline heading per round kind. Keys are `RoundKind`. */
    roundKinds: {
      generate: "Code Generation",
      drift: "Drift Analysis",
      import: "Import",
      apply: "Terraform Apply",
    },
    /**
     * Timeline row heading per working status. Keys are `SessionStatus`, and
     * the set is deliberately partial: the statuses left out (`started`,
     * `apply`, and the resting ones) read fine capitalised, so they fall
     * back to the status name itself.
     */
    statusLabels: {
      filtering: "Request acceptance",
      generating: "Generating Infrastructure as Code",
      validating: "Validating infrastructure configuration",
      reconciling: "Reconciling drift state",
      report: "Constructing a final report",
    },
    /**
     * Appended to a round heading for non-success resting states; success
     * needs no words. Keys are `SessionStatus`, and the set is deliberately
     * partial — any status absent here renders no suffix.
     */
    roundOutcomeSuffixes: {
      failed: " — Failed",
      uncompleted: " — Incomplete",
    },
    /** Marks a drift round that targeted named resources. */
    roundPartialSuffix: " (partial)",
    /** Heads the resource list in an opened plan artifact. */
    artifactTargets: "Targets",
    /** Pluralised noun for a plan row's count chip: "3 targets", "1 target". */
    artifactTargetCount: { one: "target", other: "targets" },
    /**
     * Verb prefixing an artifact row's `aria-label`. The row is a button
     * whose only text is the artifact's name, so the label has to say
     * what activating it does — sighted users get that from the eye icon.
     */
    artifactOpen: "View",
    /**
     * Labels for an artifact row. Generate reports fall back to the generic
     * `report`; the other report kinds announce themselves explicitly.
     */
    artifactLabels: {
      report: "Report",
      applyReport: "Apply Report",
      driftReport: "Drift Report",
      importReport: "Import Report",
      complianceCheck: "Compliance Check",
      terraformPlan: "Terraform Plan",
      driftOperation: "Drift Operation",
    },
  },

  admin: {
    searchPlaceholder: "Search by user or project...",
    noSessions: "No sessions found",
    sessionNotFound: "Session not found",
    loadingSession: "Loading session...",
    loadingArtifact: "Loading artifact...",
    artifactError: "Failed to load artifact",
    backToSessions: "Back to sessions",
    conversationHistory: "Conversation History",
  },
} as const;
