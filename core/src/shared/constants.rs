// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Enumerations shared by every layer.
//!
//! Each variant carries two spellings: its `value` (what the HTTP API,
//! templates and caches speak) and its `name` (what Postgres stores — the
//! enum types were created by SQLAlchemy, which persists Python enum
//! names).

use serde::{Deserialize, Deserializer, Serialize, Serializer};

macro_rules! py_enum {
    (
        $(#[$meta:meta])*
        $name:ident { $($variant:ident => ($pyname:literal, $value:literal)),+ $(,)? }
    ) => {
        $(#[$meta])*
        #[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
        pub enum $name { $($variant),+ }

        impl $name {
            pub const ALL: &'static [$name] = &[$($name::$variant),+];

            /// The Python enum member's `.value`.
            pub fn value(self) -> &'static str {
                match self { $($name::$variant => $value),+ }
            }

            /// The Python enum member's `.name`.
            pub fn name(self) -> &'static str {
                match self { $($name::$variant => $pyname),+ }
            }

            pub fn from_value(v: &str) -> Option<Self> {
                match v { $($value => Some($name::$variant),)+ _ => None }
            }

            pub fn from_name(n: &str) -> Option<Self> {
                match n { $($pyname => Some($name::$variant),)+ _ => None }
            }

            /// Pydantic's enum error listing: `'a', 'b' or 'c'`.
            pub fn expected() -> String {
                let quoted: Vec<String> = Self::ALL.iter().map(|v| format!("'{}'", v.value())).collect();
                match quoted.len() {
                    0 => String::new(),
                    1 => quoted[0].clone(),
                    n => format!("{} or {}", quoted[..n - 1].join(", "), quoted[n - 1]),
                }
            }
        }

        impl Serialize for $name {
            fn serialize<S: Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
                s.serialize_str(self.value())
            }
        }

        impl<'de> Deserialize<'de> for $name {
            fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
                let raw = String::deserialize(d)?;
                $name::from_value(&raw).ok_or_else(|| {
                    serde::de::Error::custom(format!("invalid {} value '{}'", stringify!($name), raw))
                })
            }
        }

        impl std::fmt::Display for $name {
            fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                f.write_str(self.value())
            }
        }
    };
}

py_enum! {
    /// Operation roles; definition order is the hierarchy.
    OperationRole { Developer => ("DEVELOPER", "developer"), Devops => ("DEVOPS", "devops") }
}

py_enum! {
    /// Admin-panel roles; definition order is the hierarchy.
    PanelRole { Viewer => ("VIEWER", "viewer"), Editor => ("EDITOR", "editor"), Admin => ("ADMIN", "admin") }
}

impl OperationRole {
    pub fn at_least(self, minimum: OperationRole) -> bool {
        self >= minimum
    }
}

impl PanelRole {
    pub fn at_least(self, minimum: PanelRole) -> bool {
        self >= minimum
    }
}

py_enum! {
    TerraformProvider {
        Azure => ("AZURE", "azure"),
        Gcp => ("GCP", "gcp"),
        Aws => ("AWS", "aws"),
        Oci => ("OCI", "oci"),
        K8s => ("K8S", "kubernetes"),
        Vmware => ("VMWARE", "vmware"),
    }
}

py_enum! {
    ReportType {
        Generate => ("GENERATE", "generate"),
        Drift => ("DRIFT", "drift"),
        Import => ("IMPORT", "import"),
        Apply => ("APPLY", "apply"),
    }
}

py_enum! {
    OperationType {
        Generate => ("GENERATE", "generate"),
        Drift => ("DRIFT", "drift"),
        Import => ("IMPORT", "import"),
    }
}

py_enum! {
    /// All possible Session states.
    SessionStatus {
        Started => ("STARTED", "started"),
        Filtering => ("FILTERING", "filtering"),
        Generating => ("GENERATING", "generating"),
        Validating => ("VALIDATING", "validating"),
        Reconciling => ("RECONCILING", "reconciling"),
        Report => ("REPORT", "report"),
        Apply => ("APPLY", "apply"),
        Completed => ("COMPLETED", "completed"),
        Uncompleted => ("UNCOMPLETED", "uncompleted"),
        Failed => ("FAILED", "failed"),
    }
}

py_enum! {
    /// Defines all possible base template prompts.
    PromptsLibrary {
        RequestsFilter => ("REQUESTS_FILTER", "requests_filter"),
        TaskSplitter => ("TASK_SPLITTER", "task_splitter"),
        FilterReconciliation => ("FILTER_RECONCILIATION", "filter_reconciliation"),
        FilterDriftExceptions => ("FILTER_DRIFT_EXCEPTIONS", "filter_drift_exceptions"),
        PromptCompositor => ("PROMPT_COMPOSITOR", "prompt_compositor"),
        IacGenerator => ("IAC_GENERATOR", "iac_generator"),
        ImportFilter => ("IMPORT_FILTER", "import_filter"),
        ImportExceptions => ("IMPORT_EXCEPTIONS", "import_exceptions"),
        ImportAddresses => ("IMPORT_ADDRESSES", "import_addresses"),
        TargetGenerator => ("TARGET_GENERATOR", "target_generator"),
        ReportGenerator => ("REPORT_GENERATOR", "report_generator"),
        PrGenerator => ("PR_GENERATOR", "pr_generator"),
        ComplianceChecker => ("COMPLIANCE_CHECKER", "compliance_checker"),
        StatusUpdate => ("STATUS_UPDATE", "status_update"),
        ChatReply => ("CHAT_REPLY", "chat_reply"),
    }
}

py_enum! {
    /// Defines different contexts where tools can be used.
    ToolContext {
        RequestsFilter => ("REQUESTS_FILTER", "requests_filter"),
        PromptCompositor => ("PROMPT_COMPOSITOR", "prompt_compositor"),
        TargetGenerator => ("TARGET_GENERATOR", "target_generator"),
        ReportGenerator => ("REPORT_GENERATOR", "report_generator"),
        PrGenerator => ("PR_GENERATOR", "pr_generator"),
        FileOperations => ("FILE_OPERATIONS", "file_operations"),
        WorkspaceInspection => ("WORKSPACE_INSPECTION", "workspace_inspection"),
        ExternalInformation => ("EXTERNAL_INFORMATION", "external_information"),
        TaskSplitter => ("TASK_SPLITTER", "task_splitter"),
        FilterReconciliation => ("FILTER_RECONCILIATION", "filter_reconciliation"),
        GeneralTaskCompletion => ("GENERAL_TASK_COMPLETION", "general_task_completion"),
        ImportAddresses => ("IMPORT_ADDRESSES", "import_addresses"),
        ComplianceCheck => ("COMPLIANCE_CHECK", "compliance_check"),
    }
}

impl ToolContext {
    /// `str(ToolContext.X)` as it appears in error messages.
    pub fn py_str(self) -> String {
        format!("ToolContext.{}", self.name())
    }
}

py_enum! {
    /// Defines all the supported git providers.
    GitProviderName {
        Github => ("GITHUB", "github.com"),
        AzureDevops => ("AZURE_DEVOPS", "dev.azure.com"),
        Gitlab => ("GITLAB", "gitlab.com"),
    }
}

py_enum! {
    /// Defines all the supported object-storage backends for artifacts.
    ObjectStorageProvider {
        Rustfs => ("RUSTFS", "rustfs"),
        S3 => ("S3", "s3"),
        StorageAccount => ("STORAGE_ACCOUNT", "storage_account"),
    }
}

py_enum! {
    /// Defines all possible content types for artifact upload.
    ContentType { Text => ("TEXT", "text/plain"), Json => ("JSON", "application/json") }
}

py_enum! {
    /// Defines all possible tracer projects (a Phoenix project is a group of traces).
    TracerProject {
        DevTerraformDay2 => ("DEV_TERRAFORM_DAY2", "dev-terraform-day2"),
        DevTerraformDrift => ("DEV_TERRAFORM_DRIFT", "dev-terraform-drift"),
        DevTerraformImport => ("DEV_TERRAFORM_IMPORT", "dev-terraform-import"),
        PreTerraformDay2 => ("PRE_TERRAFORM_DAY2", "pre-terraform-day2"),
        PreTerraformDrift => ("PRE_TERRAFORM_DRIFT", "pre-terraform-drift"),
        PreTerraformImport => ("PRE_TERRAFORM_IMPORT", "pre-terraform-import"),
        ProTerraformDay2 => ("PRO_TERRAFORM_DAY2", "pro-terraform-day2"),
        ProTerraformDrift => ("PRO_TERRAFORM_DRIFT", "pro-terraform-drift"),
        ProTerraformImport => ("PRO_TERRAFORM_IMPORT", "pro-terraform-import"),
    }
}

py_enum! {
    /// Selects the target generator template file: target_{value}_generator.jinja
    TargetGenerationMode { Session => ("SESSION", "session"), Drift => ("DRIFT", "drift") }
}

/// Deployment tiers; also the Phoenix tags every seeded prompt version gets.
pub const ENVIRONMENTS: [&str; 3] = ["development", "staging", "production"];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hierarchy_follows_definition_order() {
        assert!(OperationRole::Devops.at_least(OperationRole::Developer));
        assert!(!OperationRole::Developer.at_least(OperationRole::Devops));
        assert!(PanelRole::Admin.at_least(PanelRole::Editor));
        assert!(!PanelRole::Viewer.at_least(PanelRole::Editor));
    }

    #[test]
    fn pydantic_expected_listing() {
        assert_eq!(
            TerraformProvider::expected(),
            "'azure', 'gcp', 'aws', 'oci', 'kubernetes' or 'vmware'"
        );
        assert_eq!(OperationRole::expected(), "'developer' or 'devops'");
    }
}
