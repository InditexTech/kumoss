// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Detects Terraform root modules by inspecting the git tree metadata of a
//! blobless, checkout-less clone.

use std::collections::{BTreeMap, BTreeSet};

use crate::domain::ports::Git;
use crate::infrastructure::filesystem::git::GitUtils;
use crate::shared::config::SystemConfig;
use crate::shared::error::{AppError, AppResult};
use crate::shared::urls::safe_uri;

const EXCLUDED_SEGMENTS: [&str; 4] = ["modules", "examples", "example", ".terraform"];
const ROOT_MARKERS: [&str; 6] = [
    "main.tf",
    "provider.tf",
    "providers.tf",
    "backend.tf",
    "terraform.tf",
    "versions.tf",
];

fn split_parent(path: &str) -> (String, String) {
    match path.rsplit_once('/') {
        Some((parent, name)) => (if parent.is_empty() { "/".into() } else { parent.into() }, name.into()),
        None => (".".into(), path.into()),
    }
}

/// The Terraform root-module heuristic over a flat file listing: sorted
/// POSIX directory paths.
pub fn find_roots(file_paths: &[String]) -> Vec<String> {
    // Group filenames by parent directory.
    let mut dir_files: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    for path in file_paths {
        let (parent, name) = split_parent(path);
        dir_files.entry(parent).or_default().insert(name);
    }
    // Candidates: directories with a *.tf file, minus banned segments.
    let candidates: BTreeSet<String> = dir_files
        .iter()
        .filter(|(_, names)| names.iter().any(|n| n.ends_with(".tf")))
        .map(|(d, _)| d.clone())
        .filter(|d| !d.split('/').any(|seg| EXCLUDED_SEGMENTS.contains(&seg)))
        .collect();

    let has_tfvars = |names: &BTreeSet<String>| {
        names
            .iter()
            .any(|n| n.ends_with(".tfvars") || n.ends_with(".tfvars.json"))
    };
    let has_marker = |names: &BTreeSet<String>| names.iter().any(|n| ROOT_MARKERS.contains(&n.as_str()));
    let is_leaf = |d: &str| {
        let prefix = format!("{d}/");
        !candidates.iter().any(|other| other.starts_with(&prefix))
    };

    // Pass 1: directories that qualify via markers or tfvars.
    let marker_roots: BTreeSet<String> = candidates
        .iter()
        .filter(|d| {
            let names = &dir_files[*d];
            has_tfvars(names) || has_marker(names)
        })
        .cloned()
        .collect();
    let under_existing_root = |d: &str| marker_roots.iter().any(|root| d.starts_with(&format!("{root}/")));

    // Pass 2: leaves not nested under an existing root.
    let mut roots: Vec<String> = marker_roots.iter().cloned().collect();
    for d in &candidates {
        if !marker_roots.contains(d) && is_leaf(d) && !under_existing_root(d) {
            roots.push(d.clone());
        }
    }
    roots.sort();
    roots
}

pub struct IacRootDetector {
    cfg: &'static SystemConfig,
}

impl IacRootDetector {
    pub fn new(cfg: &'static SystemConfig) -> Self {
        Self { cfg }
    }

    pub async fn detect_roots(&self, repo_uri: &str) -> AppResult<Vec<String>> {
        let clone_dir = tempfile::Builder::new()
            .prefix("iac-root-")
            .tempdir()
            .map_err(|e| AppError::internal(e.to_string()))?;
        let git = GitUtils::new(repo_uri, Some(clone_dir.path()), self.cfg);
        if !git
            .clone_repository(repo_uri, "repo", &["--filter=blob:none", "--no-checkout"], 60)
            .await
        {
            return Err(AppError::repository_unreachable(502));
        }
        let files = git.ls_tree(&clone_dir.path().join("repo")).await?;
        let roots = find_roots(&files);
        tracing::info!("Scanned {} — found {} root(s)", safe_uri(repo_uri), roots.len());
        Ok(roots)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn s(v: &[&str]) -> Vec<String> {
        v.iter().map(|x| x.to_string()).collect()
    }

    #[test]
    fn heuristic() {
        let files = s(&[
            "envs/dev/main.tf",
            "envs/dev/terraform.tfvars",
            "envs/dev/sub/extra.tf",
            "modules/net/main.tf",
            "stacks/a/network.tf",
            "stacks/a/b/x.tf",
            "examples/basic/main.tf",
            "README.md",
            "root.tf",
        ]);
        assert_eq!(find_roots(&files), s(&[".", "envs/dev", "stacks/a/b"]));
    }

    #[test]
    fn leaf_directories_count() {
        assert_eq!(find_roots(&s(&["infra/vpc.tf"])), s(&["infra"]));
        assert_eq!(find_roots(&s(&["docs/readme.md"])), Vec::<String>::new());
    }
}
