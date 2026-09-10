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
    highImpactTitle: "High Impact Deployment",
    highImpactMessage:
      "This deployment involves high-impact changes that could significantly affect your infrastructure. The session has been blocked and our support team notified. A specialist will review your request and contact you shortly.",
  },

  applyResults: {
    success: "Apply finished successfully",
    partial: "Apply partially completed",
    failure: "Apply failed",
    taskLabel: "Task:",
    taskValue: "Terraform Apply",
    completedLabel: "Completed:",
    errorMessage:
      "Infrastructure application error. The Nebula AI team can help you resolve it.",
    viewResources: "View Resources",
  },

  support: {
    buttonText: "CONTACT SUPPORT",
    creatingNotification: "Sending support request...",
    creatingButton: "SENDING SUPPORT REQUEST",
    groupCreated: "Support request sent. The team has been notified.",
    sendFailed: "Support request could not be sent.",
    openLink: "Click here to open Nebula AI",
    noEmailError: "Error: No user email found. Please login again.",
    tooltip:
      "Contact the Nebula team - they will help you to: \
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
    loadingRepository: "Resolving repository...",
    loadingPermissions: "Verifying permissions...",
    tryAgain: "Try again",
    startOver: "Start over",
    ariaQuery: "Describe your infrastructure request",
    ariaRepositoryUrl: "Repository URL",
    ariaIacPath: "IaC path",
    ariaProvider: "Cloud provider",
    ariaCloudScope: "Cloud scope",
    promptQuery: "What do you need?",
    promptRepository: "What is the repository URL?",
    promptIacPath: "Which IaC path?",
    promptProvider: "Which cloud provider?",
    promptCloudScope: "What is the cloud scope?",
    checkingPermissions: "Checking permissions on",
    placeholderQuery: "Type your request...",
    placeholderRepository: "https://dev.azure.com/org/project/_git/repo",
    placeholderCloudScope: "azure-subscription-id, gcp-project-id",
    // scope_id in each provider's own jargon; keys mirror TERRAFORM_PROVIDERS
    scopeByProvider: {
      azure: {
        label: "Subscription ID",
        prompt: "What is the Azure subscription ID?",
        placeholder: "azure-subscription-id",
      },
      gcp: {
        label: "Project ID",
        prompt: "What is the GCP project ID?",
        placeholder: "my-gcp-project-id",
      },
      aws: {
        label: "Account ID",
        prompt: "What is the AWS account ID?",
        placeholder: "123456789012",
      },
      oci: {
        label: "Compartment ID",
        prompt: "What is the OCI compartment name?",
        placeholder: "my-compartment",
      },
      kubernetes: {
        label: "Namespace",
        prompt: "Which Kubernetes namespace?",
        placeholder: "my-namespace",
      },
    },
    resolveError: "Could not resolve repository. Please try again.",
    scanError: "Could not scan repository for IaC paths. Please try again.",
    noIacPaths:
      "No IaC paths found in this repository. Please check the repository and try again.",
  },

  sessions: {
    pageTitle: "Sessions",
    searchPlaceholder: "Search User or Project",
    noSessions: "No sessions found",
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
