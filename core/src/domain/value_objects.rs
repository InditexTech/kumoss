// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

use std::path::PathBuf;

use serde::{Deserialize, Serialize};

use crate::shared::constants::{SessionStatus, TerraformProvider};

/// A session status and its associated message.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Status {
    pub status: SessionStatus,
    pub msg: String,
}

/// Write-once workspace fields captured at session creation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WorkspaceFacts {
    pub uri: String,
    pub branch: String,
    pub root_path: Option<String>,
}

/// Write-once terraform-provider fields captured at creation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProviderFacts {
    pub provider: TerraformProvider,
    pub scope_id: String,
}

/// Best practices and conventions captured at PROMPT_COMPOSITOR generation:
/// template names and terraform resource name conventions.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Conventions {
    pub templates: Vec<String>,
    pub abbreviations: Vec<String>,
}

impl Conventions {
    pub fn empty() -> Self {
        Self::default()
    }
}

/// The identity of a plan artifact a terraform run left on disk.
///
/// `show` reads it back and `apply` executes it. `commit` fingerprints the
/// workspace as it stood when the plan was produced; a holder whose
/// fingerprint no longer matches holds a stale plan. `stdout` is the plan
/// text, carried along for the drift read; it is not part of the identity.
#[derive(Debug, Clone)]
pub struct PlanRef {
    pub workspace: PathBuf,
    pub plan_file: String,
    pub targets: Vec<String>,
    pub commit: String,
    pub stdout: String,
}

impl PartialEq for PlanRef {
    fn eq(&self, other: &Self) -> bool {
        self.workspace == other.workspace
            && self.plan_file == other.plan_file
            && self.targets == other.targets
            && self.commit == other.commit
    }
}

impl PlanRef {
    /// The dataclass repr, `stdout` excluded (`repr=False`).
    pub fn py_repr(&self) -> String {
        format!(
            "PlanRef(workspace=PosixPath({}), plan_file={}, targets=({}), commit={})",
            crate::shared::pyfmt::repr_str(&self.workspace.to_string_lossy()),
            crate::shared::pyfmt::repr_str(&self.plan_file),
            {
                let items: Vec<String> = self.targets.iter().map(|t| crate::shared::pyfmt::repr_str(t)).collect();
                if items.len() == 1 {
                    format!("{},", items[0])
                } else {
                    items.join(", ")
                }
            },
            crate::shared::pyfmt::repr_str(&self.commit),
        )
    }
}

/// Identity claims extracted from a validated token. `email_verified` is
/// true only when the token carried an `email` claim together with
/// `email_verified: true`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TokenClaims {
    pub issuer: String,
    pub subject: String,
    pub email: Option<String>,
    pub name: Option<String>,
    pub email_verified: bool,
}

/// One web search hit with the page content read behind it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SearchResult {
    pub title: String,
    pub url: String,
    pub content: String,
}

/// One page's condensed content plus its position in the engine order.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PageSummary {
    /// 0-based, as the ids the selection inference returns.
    pub index: usize,
    pub result: SearchResult,
    pub summary: String,
}

/// One resource or data source page of a provider version's registry docs.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TerraformDoc {
    /// `<namespace>/<name>`, e.g. `hashicorp/aws`.
    pub source: String,
    /// The exact provider version the page belongs to.
    pub version: String,
    pub resource_type: String,
    pub url: String,
    /// The page markdown, frontmatter removed.
    pub content: String,
}
