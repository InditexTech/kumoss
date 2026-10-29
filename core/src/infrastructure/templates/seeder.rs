// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Bootstraps Phoenix with the example prompts Kumoss's IaC flows need.
//!
//! Runs at startup. A missing prompt is created. The version the seeder last
//! pushed carries the `seed` tag; when its text differs from the seed on
//! disk, the seed is pushed again and the environment tags still on that
//! version move with it, so an improved seed reaches upgraded installs while
//! an environment tag an operator points at their own version never moves.
//!
//! Each seed lives at `<seed_dir>/<scope>/<type>/<name>.yaml` and carries
//! the prompt body plus an optional description; scope, type and name come
//! from the path, so a misfiled prompt cannot lie about its identity.

use std::path::{Path, PathBuf};
use std::sync::LazyLock;
use std::time::Duration;

use regex::Regex;
use serde_json::{Value, json};

use crate::infrastructure::templates::phoenix::{PhoenixClient, PhoenixError};
use crate::shared::constants::ENVIRONMENTS;
use crate::shared::error::{AppError, AppResult, ErrorKind};

const VALID_SCOPES: [&str; 7] = ["general", "azure", "gcp", "aws", "oci", "kubernetes", "vmware"];
const VALID_TYPES: [&str; 3] = ["guidelines", "resources", "compliance"];
static NAME_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[a-z0-9_]+$").unwrap());

const CONNECT_BACKOFF: [f64; 10] = [0.5, 1.0, 2.0, 4.0, 5.0, 5.0, 5.0, 5.0, 7.0, 10.0];
const SEED_MODEL_NAME: &str = "kumoss-seed";
/// On the version the seeder last pushed for each prompt.
const SEED_TAG: &str = "seed";

fn load_error(message: String) -> AppError {
    AppError::kind(ErrorKind::PromptSeedLoad, message, 500)
}

fn push_error(message: String, code: u16) -> AppError {
    AppError::kind(ErrorKind::PromptSeedPush, message, code)
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SeedEntry {
    pub scope: String,
    pub kind: String,
    pub name: String,
    pub body: String,
    pub description: Option<String>,
    pub source: PathBuf,
}

impl SeedEntry {
    pub fn qualified_name(&self) -> String {
        format!("{}-{}-{}", self.scope, self.kind, self.name)
    }
}

fn sorted_scope_list(items: &[&str]) -> String {
    let mut v: Vec<&str> = items.to_vec();
    v.sort();
    crate::shared::pyfmt::repr_str_list(&v)
}

/// Every `*.yaml` under `dir`, sorted by path components like `sorted(rglob)`.
fn yaml_files(dir: &Path) -> Vec<PathBuf> {
    let mut out = Vec::new();
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&d) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                stack.push(path.clone());
            }
            if path
                .file_name()
                .and_then(|n| n.to_str())
                .is_some_and(|n| n.ends_with(".yaml"))
                && path.is_file()
            {
                out.push(path);
            }
        }
    }
    out.sort_by(|a, b| {
        let pa: Vec<String> = a
            .components()
            .map(|c| c.as_os_str().to_string_lossy().into_owned())
            .collect();
        let pb: Vec<String> = b
            .components()
            .map(|c| c.as_os_str().to_string_lossy().into_owned())
            .collect();
        pa.cmp(&pb)
    });
    out
}

/// Walks a seed directory and returns validated entries.
pub fn load_seeds(seed_dir: &Path) -> AppResult<Vec<SeedEntry>> {
    if !seed_dir.is_dir() {
        return Err(load_error(format!(
            "Seed directory does not exist: {}",
            seed_dir.display()
        )));
    }
    let mut entries = Vec::new();
    let mut seen: std::collections::HashMap<String, PathBuf> = std::collections::HashMap::new();
    for path in yaml_files(seed_dir) {
        let entry = parse_seed(seed_dir, &path)?;
        let qn = entry.qualified_name();
        if let Some(prev) = seen.get(&qn) {
            return Err(load_error(format!(
                "Duplicate qualified name '{qn}' from {} and {}",
                path.display(),
                prev.display()
            )));
        }
        seen.insert(qn, path);
        entries.push(entry);
    }
    Ok(entries)
}

fn parse_seed(seed_dir: &Path, path: &Path) -> AppResult<SeedEntry> {
    let rel = path.strip_prefix(seed_dir).map_err(|_| {
        load_error(format!(
            "Seed file {} is not under {}",
            path.display(),
            seed_dir.display()
        ))
    })?;
    let parts: Vec<String> = rel
        .components()
        .map(|c| c.as_os_str().to_string_lossy().into_owned())
        .collect();
    if parts.len() != 3 {
        return Err(load_error(format!(
            "Seed file path must be <scope>/<type>/<name>.yaml; got {} (relative: {})",
            path.display(),
            parts.join("/")
        )));
    }
    let (scope, kind, filename) = (&parts[0], &parts[1], &parts[2]);
    if !VALID_SCOPES.contains(&scope.as_str()) {
        return Err(load_error(format!(
            "Invalid scope '{scope}' in {}; expected one of {}",
            path.display(),
            sorted_scope_list(&VALID_SCOPES)
        )));
    }
    if !VALID_TYPES.contains(&kind.as_str()) {
        return Err(load_error(format!(
            "Invalid type '{kind}' in {}; expected one of {}",
            path.display(),
            sorted_scope_list(&VALID_TYPES)
        )));
    }
    let name = filename.strip_suffix(".yaml").unwrap_or(filename).to_string();
    if !NAME_RE.is_match(&name) {
        return Err(load_error(format!(
            "Invalid prompt name '{name}' in {}; must match {}",
            path.display(),
            NAME_RE.as_str()
        )));
    }
    let text = std::fs::read_to_string(path)
        .map_err(|e| load_error(format!("YAML parse error in {}: {e}", path.display())))?;
    let data = crate::shared::yaml::safe_load(&text)
        .map_err(|e| load_error(format!("YAML parse error in {}: {e}", path.display())))?;
    let Value::Object(map) = &data else {
        let type_name = match &data {
            Value::Null => "NoneType",
            Value::Bool(_) => "bool",
            Value::Number(n) if n.is_f64() => "float",
            Value::Number(_) => "int",
            Value::String(_) => "str",
            Value::Array(_) => "list",
            Value::Object(_) => "dict",
        };
        return Err(load_error(format!(
            "Top-level YAML in {} must be a mapping (got {type_name})",
            path.display()
        )));
    };
    let body = match map.get("body") {
        Some(Value::String(s)) if !crate::shared::pyfmt::strip(s).is_empty() => s.clone(),
        _ => {
            return Err(load_error(format!(
                "'body' in {} must be a non-empty string",
                path.display()
            )));
        }
    };
    let description = match map.get("description") {
        None | Some(Value::Null) => None,
        Some(Value::String(s)) => Some(s.clone()),
        Some(_) => {
            return Err(load_error(format!(
                "'description' in {} must be a string when present",
                path.display()
            )));
        }
    };
    Ok(SeedEntry {
        scope: scope.clone(),
        kind: kind.clone(),
        name,
        body,
        description,
        source: path.to_path_buf(),
    })
}

/// The single text message the seeder writes, or None for any other shape
/// (which therefore never matches a seed).
fn version_text(data: &Value) -> Option<String> {
    let messages = data.pointer("/template/messages")?.as_array()?;
    if messages.len() != 1 {
        return None;
    }
    let content = messages[0].get("content")?;
    if let Some(s) = content.as_str() {
        return Some(s.to_string());
    }
    let parts = content.as_array()?;
    if parts.len() != 1 || parts[0].get("type").and_then(Value::as_str) != Some("text") {
        return None;
    }
    parts[0].get("text")?.as_str().map(str::to_string)
}

fn version_id(data: &Value) -> Option<String> {
    data.get("id").and_then(Value::as_str).map(str::to_string)
}

pub struct PromptSeeder {
    seed_dir: PathBuf,
    client: PhoenixClient,
}

impl PromptSeeder {
    pub fn new(seed_dir: PathBuf, phoenix_base_url: &str) -> Self {
        Self {
            seed_dir,
            client: PhoenixClient::new(phoenix_base_url),
        }
    }

    /// Load the seeds, create the ones missing from Phoenix and update the
    /// ones whose `seed` version differs from disk.
    pub async fn ensure_seeded(&self) -> AppResult<()> {
        let entries = load_seeds(&self.seed_dir)?;
        tracing::info!(
            "Prompt seeder loaded {} entries from disk (tags={})",
            entries.len(),
            ENVIRONMENTS.join(", ")
        );
        self.probe_phoenix().await?;
        let (mut created, mut updated, mut unchanged) = (0, 0, 0);
        for entry in &entries {
            match self.seed_version(entry).await? {
                None => {
                    let mut tags: Vec<&str> = ENVIRONMENTS.to_vec();
                    tags.push(SEED_TAG);
                    self.push(entry, &tags, None).await?;
                    created += 1;
                }
                Some(seed) if version_text(&seed).as_deref() != Some(entry.body.as_str()) => {
                    let (owned, current_id) = self.owned_tags(entry, &seed).await?;
                    let mut tags: Vec<&str> = owned;
                    tags.push(SEED_TAG);
                    self.push(entry, &tags, current_id).await?;
                    updated += 1;
                }
                Some(_) => unchanged += 1,
            }
        }
        tracing::info!("Prompt seeding complete: {created} created, {updated} updated, {unchanged} unchanged");
        Ok(())
    }

    /// Hit Phoenix once, retrying on connection-level failures only:
    /// compose's `depends_on` does not wait for readiness. The probe name
    /// must start with an alphanumeric character (Phoenix 422s otherwise).
    async fn probe_phoenix(&self) -> AppResult<()> {
        let probe = "kumoss_seed_probe_does_not_exist";
        let mut last_err = String::new();
        for (attempt, delay) in CONNECT_BACKOFF.iter().enumerate() {
            match self.client.get_prompt(probe, None).await {
                Ok(_) | Err(PhoenixError::NotFound(_)) => return Ok(()),
                Err(PhoenixError::Connect(e)) => {
                    tracing::info!(
                        "Phoenix not ready yet (attempt {}/{}): {e}",
                        attempt + 1,
                        CONNECT_BACKOFF.len()
                    );
                    last_err = e;
                    tokio::time::sleep(Duration::from_secs_f64(*delay)).await;
                }
                Err(e) => return Err(push_error(format!("Phoenix probe failed: {e}"), 502)),
            }
        }
        Err(push_error(
            format!(
                "Phoenix unreachable after {} attempts: {last_err}",
                CONNECT_BACKOFF.len()
            ),
            504,
        ))
    }

    /// The version `tag` points at, or the latest one; None when there is none.
    async fn get(&self, entry: &SeedEntry, tag: Option<&str>) -> AppResult<Option<Value>> {
        match self.client.get_prompt(&entry.qualified_name(), tag).await {
            Ok(v) => {
                if v.pointer("/template/type").and_then(Value::as_str) != Some("chat") {
                    return Err(AppError::internal(format!(
                        "prompt {} is not a chat template",
                        entry.qualified_name()
                    )));
                }
                Ok(Some(v))
            }
            Err(PhoenixError::NotFound(_)) => Ok(None),
            Err(e) => Err(push_error(
                format!(
                    "Error reading '{}'{}: {e}",
                    entry.qualified_name(),
                    tag.map(|t| format!(" tagged '{t}'")).unwrap_or_default()
                ),
                502,
            )),
        }
    }

    /// The version tagged `seed`, or None when the prompt is missing. A
    /// prompt without the tag has its latest version taken as the seeder's.
    async fn seed_version(&self, entry: &SeedEntry) -> AppResult<Option<Value>> {
        if let Some(seed) = self.get(entry, Some(SEED_TAG)).await? {
            return Ok(Some(seed));
        }
        let Some(latest) = self.get(entry, None).await? else {
            return Ok(None);
        };
        let id = version_id(&latest).unwrap_or_default();
        self.tag(entry, &id, &[SEED_TAG]).await?;
        tracing::info!(
            "Tagged the latest version of {} as '{SEED_TAG}'",
            entry.qualified_name()
        );
        Ok(Some(latest))
    }

    /// The environment tags still on the `seed` version, and the id of the
    /// latest version when it already holds the text on disk (an earlier
    /// boot pushed it and failed before moving `seed`, which moves last).
    async fn owned_tags(&self, entry: &SeedEntry, seed: &Value) -> AppResult<(Vec<&'static str>, Option<String>)> {
        let seed_id = version_id(seed);
        let mut owned = Vec::new();
        for tag in ENVIRONMENTS {
            if let Some(v) = self.get(entry, Some(tag)).await?
                && version_id(&v) == seed_id
            {
                owned.push(tag);
            }
        }
        let latest = self.get(entry, None).await?;
        let current_id = match latest {
            Some(l) if version_id(&l) != seed_id && version_text(&l).as_deref() == Some(entry.body.as_str()) => {
                version_id(&l)
            }
            _ => None,
        };
        Ok((owned, current_id))
    }

    async fn push(&self, entry: &SeedEntry, tags: &[&str], version_id: Option<String>) -> AppResult<()> {
        let id = match version_id {
            Some(id) => id,
            None => self.create(entry).await?,
        };
        self.tag(entry, &id, tags).await?;
        tracing::info!("Pushed prompt: {} (tags={})", entry.qualified_name(), tags.join(", "));
        Ok(())
    }

    /// Tag in order, so `seed` (passed last) moves only once every
    /// environment tag has.
    async fn tag(&self, entry: &SeedEntry, version_id: &str, tags: &[&str]) -> AppResult<()> {
        for (i, tag) in tags.iter().enumerate() {
            if let Err(e) = self.client.tag_version(version_id, tag).await {
                return Err(push_error(
                    format!(
                        "Failed to tag '{}' (version {version_id}) with '{tag}': {e}. The version now exists; tag that version by hand with: {}",
                        entry.qualified_name(),
                        tags[i..].join(", ")
                    ),
                    502,
                ));
            }
        }
        Ok(())
    }

    async fn create(&self, entry: &SeedEntry) -> AppResult<String> {
        let mut version = json!({
            "model_provider": "OPENAI",
            "model_name": SEED_MODEL_NAME,
            "template": {
                "messages": [{"role": "user", "content": [{"type": "text", "text": entry.body}]}],
                "type": "chat",
            },
            "template_type": "CHAT",
            "template_format": "NONE",
            "invocation_parameters": {"type": "openai", "openai": {}},
        });
        if let Some(d) = &entry.description {
            version["description"] = json!(d);
        }
        let created = self
            .client
            .create_prompt(&entry.qualified_name(), entry.description.as_deref(), version)
            .await
            .map_err(|e| {
                push_error(
                    format!("Failed to create prompt '{}': {e}", entry.qualified_name()),
                    502,
                )
            })?;
        match version_id(&created).filter(|id| !id.is_empty()) {
            Some(id) => Ok(id),
            None => Err(push_error(
                format!(
                    "Phoenix returned no version id for '{}'; cannot tag",
                    entry.qualified_name()
                ),
                502,
            )),
        }
    }
}

/// The seed directory: `KUMOSS_SEED_DIR`, else `prompts/seed` next to the
/// executable, else the source tree's.
pub fn default_seed_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("KUMOSS_SEED_DIR")
        && !dir.is_empty()
    {
        return PathBuf::from(dir);
    }
    if let Some(dir) = std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(|p| p.join("prompts/seed")))
        && dir.is_dir()
    {
        return dir;
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("prompts/seed")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bundled_seed_catalog_loads() {
        let entries = load_seeds(&PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("prompts/seed")).expect("seeds load");
        assert!(entries.len() > 100);
        assert!(
            entries
                .iter()
                .any(|e| e.qualified_name() == "general-guidelines-terraform")
        );
        let mut names: Vec<String> = entries.iter().map(SeedEntry::qualified_name).collect();
        let before = names.len();
        names.dedup();
        assert_eq!(before, names.len());
    }

    #[test]
    fn version_text_shapes() {
        assert_eq!(
            version_text(&json!({"template": {"messages": [{"content": [{"type": "text", "text": "x"}]}]}})).as_deref(),
            Some("x")
        );
        assert_eq!(
            version_text(&json!({"template": {"messages": [{"content": "y"}]}})).as_deref(),
            Some("y")
        );
        assert_eq!(version_text(&json!({"template": {"messages": []}})), None);
    }

    #[test]
    fn rejects_misfiled_seed() {
        let dir = tempfile::tempdir().unwrap();
        let bad = dir.path().join("general/guidelines");
        std::fs::create_dir_all(&bad).unwrap();
        std::fs::write(bad.join("Bad-Name.yaml"), "body: x\n").unwrap();
        let err = load_seeds(dir.path()).unwrap_err();
        assert!(
            err.message.contains("Invalid prompt name 'Bad-Name'"),
            "{}",
            err.message
        );
    }
}
