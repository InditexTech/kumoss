// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Tool-oriented filesystem rooted at a workspace's IaC root.

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::process::Command;

use crate::domain::ports::FileSystem;
use crate::infrastructure::filesystem::oserror_repr;
use crate::infrastructure::tools::realpath;
use crate::shared::error::{AppError, AppResult, ErrorKind};
use crate::shared::pyfmt;

const SEARCH_MARKER: &str = "<<<<<<< SEARCH";
const SEPARATOR_MARKER: &str = "=======";
const REPLACE_MARKER: &str = ">>>>>>> REPLACE";

pub struct FileSystemUtils {
    root: PathBuf,
    file_ext: Vec<String>,
    backend_override_filename: String,
}

fn block_error(message: String, code: u16) -> AppError {
    AppError::kind(ErrorKind::SearchReplaceBlock, message, code)
}

/// A short single-line, quoted preview of a text for error messages.
fn snippet(text: &str) -> String {
    let stripped = pyfmt::strip(text);
    let mut first = if stripped.is_empty() {
        String::new()
    } else {
        pyfmt::splitlines(stripped).first().copied().unwrap_or("").to_string()
    };
    if pyfmt::char_len(&first) > 80 {
        first = format!("{}...", pyfmt::take_chars(&first, 80));
    }
    pyfmt::repr_str(&first)
}

/// Parse raw search/replace blocks into (search, replace) pairs.
fn parse_blocks(blocks: &str) -> AppResult<Vec<(String, String)>> {
    #[derive(PartialEq)]
    enum Section {
        None,
        Search,
        Replace,
    }
    let mut parsed: Vec<(String, String)> = Vec::new();
    let mut search_lines: Vec<&str> = Vec::new();
    let mut replace_lines: Vec<&str> = Vec::new();
    let mut section = Section::None;
    let lines = pyfmt::splitlines(blocks);
    let malformed = |parsed: &Vec<(String, String)>, line_no: usize, reason: String| {
        block_error(
            format!("Block {} (diff line {line_no}): {reason}", parsed.len() + 1),
            400,
        )
    };
    for (i, line) in lines.iter().enumerate() {
        let line_no = i + 1;
        let marker = pyfmt::strip(line);
        if marker == SEARCH_MARKER {
            if section != Section::None {
                return Err(malformed(
                    &parsed,
                    line_no,
                    format!("'{SEARCH_MARKER}' found before the previous block was closed with '{REPLACE_MARKER}'."),
                ));
            }
            section = Section::Search;
            search_lines.clear();
            replace_lines.clear();
        } else if marker == SEPARATOR_MARKER {
            if section == Section::None {
                return Err(malformed(
                    &parsed,
                    line_no,
                    format!("'{SEPARATOR_MARKER}' found outside a block; blocks must start with '{SEARCH_MARKER}'."),
                ));
            }
            if section == Section::Replace {
                return Err(malformed(
                    &parsed,
                    line_no,
                    format!("more than one '{SEPARATOR_MARKER}' separator in the same block."),
                ));
            }
            section = Section::Replace;
        } else if marker == REPLACE_MARKER {
            if section == Section::None {
                return Err(malformed(
                    &parsed,
                    line_no,
                    format!("'{REPLACE_MARKER}' found outside a block; blocks must start with '{SEARCH_MARKER}'."),
                ));
            }
            if section == Section::Search {
                return Err(malformed(
                    &parsed,
                    line_no,
                    format!("missing '{SEPARATOR_MARKER}' separator between SEARCH and REPLACE sections."),
                ));
            }
            let search = search_lines.join("\n");
            if pyfmt::strip(&search).is_empty() {
                return Err(malformed(&parsed, line_no, "SEARCH section is empty.".into()));
            }
            parsed.push((search, replace_lines.join("\n")));
            section = Section::None;
        } else if section == Section::Search {
            search_lines.push(line);
        } else if section == Section::Replace {
            replace_lines.push(line);
        } else if !marker.is_empty() && !marker.starts_with("```") {
            return Err(malformed(
                &parsed,
                line_no,
                format!(
                    "unexpected text outside a block: {}. Blocks must start with '{SEARCH_MARKER}'.",
                    snippet(line)
                ),
            ));
        }
    }
    if section != Section::None {
        return Err(malformed(
            &parsed,
            lines.len(),
            format!("block is not closed with '{REPLACE_MARKER}'."),
        ));
    }
    if parsed.is_empty() {
        return Err(block_error("No SEARCH/REPLACE blocks found in diff.".into(), 400));
    }
    Ok(parsed)
}

/// Apply search/replace blocks: each SEARCH must match exactly once.
fn process_blocks(mut content: String, blocks: &str) -> AppResult<String> {
    for (index, (search, replace)) in parse_blocks(blocks)?.into_iter().enumerate() {
        let index = index + 1;
        let occurrences = content.matches(&search).count();
        if occurrences == 0 {
            return Err(block_error(
                format!(
                    "Block {index}: SEARCH content not found in file: {}. It must match the current file content exactly; re-read the file if unsure.",
                    snippet(&search)
                ),
                404,
            ));
        }
        if occurrences > 1 {
            return Err(block_error(
                format!(
                    "Block {index}: SEARCH content matches {occurrences} locations in file: {}. Include more surrounding lines so it matches exactly one location.",
                    snippet(&search)
                ),
                400,
            ));
        }
        content = content.replacen(&search, &replace, 1);
    }
    Ok(content)
}

/// Read a file in text mode: strict UTF-8, universal newlines.
fn read_text(path: &Path) -> Result<String, String> {
    let bytes = std::fs::read(path).map_err(|e| oserror_repr(&e))?;
    match String::from_utf8(bytes) {
        Ok(s) => Ok(pyfmt::universal_newlines(&s)),
        Err(e) => {
            let pos = e.utf8_error().valid_up_to();
            Err(format!(
                "UnicodeDecodeError('utf-8', b'...', {pos}, {}, 'invalid start byte')",
                pos + 1
            ))
        }
    }
}

impl FileSystemUtils {
    /// The caller passes the actual IaC root; no discovery is performed.
    pub fn new(root: &Path, backend_override_filename: &str) -> Self {
        Self {
            root: realpath(&std::path::absolute(root).unwrap_or_else(|_| root.to_path_buf())),
            file_ext: vec!["tf".into(), "tfvars".into()],
            backend_override_filename: backend_override_filename.to_string(),
        }
    }

    fn resolve(&self, relative: &str) -> PathBuf {
        self.root.join(relative)
    }

    fn validate_extension(&self, file_name: &str) -> AppResult<()> {
        if self.file_ext.is_empty() {
            return Ok(());
        }
        let ext = if file_name.contains('.') {
            file_name.rsplit('.').next().unwrap_or("")
        } else {
            ""
        };
        if !self.file_ext.iter().any(|e| e == ext) {
            return Err(AppError::new(
                format!(
                    "File extension violation. File '{file_name}' cannot be modified. Allowed extensions: {}",
                    pyfmt::repr_str_list(&self.file_ext)
                ),
                400,
            ));
        }
        Ok(())
    }

    fn protected_globs(&self) -> Vec<String> {
        let mut names = self.protected_names();
        names.sort();
        names
            .into_iter()
            .flat_map(|n| ["--glob".to_string(), format!("!{n}")])
            .collect()
    }

    /// Immediate children of a directory, honoring the same ignore rules
    /// ripgrep applies in `search_files`, so both tools agree on what the
    /// workspace contains.
    fn visible_children(&self, dir: &Path) -> AppResult<Vec<PathBuf>> {
        let mut cmd = Command::new("rg");
        cmd.args(["--files", "--hidden", "--no-require-git"])
            .args(self.protected_globs())
            .arg(dir)
            .current_dir(dir);
        let out = cmd
            .output()
            .map_err(|e| AppError::new(format!("Failed to list directory: {}", oserror_repr(&e)), 500))?;
        let code = out.status.code().unwrap_or(-1);
        if code != 0 && code != 1 {
            let stderr = String::from_utf8_lossy(&out.stderr).into_owned();
            tracing::error!("Ripgrep error: {stderr}");
            return Err(AppError::kind(
                ErrorKind::Ripgrep,
                stderr,
                u16::try_from(code).unwrap_or(500),
            ));
        }
        let stdout = String::from_utf8_lossy(&out.stdout).into_owned();
        let mut children: BTreeSet<PathBuf> = BTreeSet::new();
        for line in pyfmt::splitlines(&stdout) {
            if let Ok(rel) = Path::new(line).strip_prefix(dir)
                && let Some(first) = rel.components().next()
            {
                children.insert(dir.join(first.as_os_str()));
            }
        }
        Ok(children.into_iter().collect())
    }
}

impl FileSystem for FileSystemUtils {
    fn project_root(&self) -> PathBuf {
        self.root.clone()
    }

    fn protected_names(&self) -> Vec<String> {
        vec![
            ".git".into(),
            ".gitignore".into(),
            self.backend_override_filename.clone(),
        ]
    }

    fn write_file(&self, target_file: &str, content: &str, is_safe: bool) -> AppResult<()> {
        let path = self.resolve(target_file);
        if is_safe {
            self.validate_extension(
                &path
                    .file_name()
                    .map(|n| n.to_string_lossy().into_owned())
                    .unwrap_or_default(),
            )?;
        }
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| {
                AppError::new(
                    format!("Error writing to file {target_file} - {}", oserror_repr(&e)),
                    500,
                )
            })?;
        }
        if path.exists() {
            tracing::warn!("The file {target_file} already exists, content will be overwritten.");
        } else {
            tracing::info!("The file {target_file} does not exist, it will be created.");
        }
        if let Err(e) = std::fs::write(&path, content) {
            let msg = format!("Error writing to file {target_file} - {}", oserror_repr(&e));
            tracing::error!("{msg}");
            return Err(AppError::new(msg, 500));
        }
        if !path.exists() {
            return Err(AppError::new(
                format!("File {target_file} was not created successfully"),
                500,
            ));
        }
        tracing::info!("Successfully wrote to file {target_file}");
        Ok(())
    }

    fn replace_in_file(&self, target_file: &str, search_replace_blocks: &str) -> AppResult<()> {
        let path = self.resolve(target_file);
        if !path.exists() {
            return Err(AppError::new(format!("File {target_file} does not exist"), 404));
        }
        self.validate_extension(
            &path
                .file_name()
                .map(|n| n.to_string_lossy().into_owned())
                .unwrap_or_default(),
        )?;
        let wrap = |repr: String| {
            tracing::error!("Error replacing content in file {target_file}: {repr}");
            AppError::new(format!("Failed to replace content in file {target_file}: {repr}"), 500)
        };
        let content = read_text(&path).map_err(wrap)?;
        let modified = match process_blocks(content, search_replace_blocks) {
            Ok(m) => m,
            Err(e) => {
                tracing::warn!(
                    "Rejected search/replace blocks for {target_file}: Error {}: {}",
                    e.code,
                    e.message
                );
                return Err(e);
            }
        };
        std::fs::write(&path, modified).map_err(|e| wrap(oserror_repr(&e)))?;
        tracing::info!("Successfully replaced content in file {target_file}");
        Ok(())
    }

    fn delete_file(&self, target_file: &str) -> AppResult<()> {
        let path = self.resolve(target_file);
        self.validate_extension(
            &path
                .file_name()
                .map(|n| n.to_string_lossy().into_owned())
                .unwrap_or_default(),
        )?;
        match std::fs::remove_file(&path) {
            Ok(()) => {
                tracing::info!("Successfully deleted file {target_file}");
                Ok(())
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Err(AppError::kind(
                ErrorKind::CustomFileNotFound,
                format!("File {target_file} does not exist"),
                404,
            )),
            Err(e) => {
                let repr = oserror_repr(&e);
                tracing::error!("Error deleting file {target_file}: {repr}");
                Err(AppError::new(
                    format!("Failed to delete file {target_file}: {repr}"),
                    500,
                ))
            }
        }
    }

    fn read_file(&self, target_file: &str) -> AppResult<String> {
        let path = self.resolve(target_file);
        let not_found = || {
            AppError::kind(
                ErrorKind::CustomFileNotFound,
                format!("File {target_file} does not exist"),
                404,
            )
        };
        if !path.exists() {
            return Err(not_found());
        }
        match read_text(&path) {
            Ok(content) => {
                tracing::info!("Successfully read file {target_file}");
                Ok(content)
            }
            Err(repr) if repr.starts_with("FileNotFoundError") => Err(not_found()),
            Err(repr) => {
                tracing::error!("Error reading file {target_file}: {repr}");
                Err(AppError::new(format!("Failed to read file {target_file}: {repr}"), 500))
            }
        }
    }

    fn list_directory(&self, relative_path: &str) -> AppResult<Vec<PathBuf>> {
        let dir = self.resolve(relative_path);
        if !dir.exists() {
            return Err(AppError::new(format!("Directory {relative_path} does not exist"), 404));
        }
        if !dir.is_dir() {
            return Err(AppError::new(format!("Path {relative_path} is not a directory"), 400));
        }
        self.visible_children(&dir)
    }

    fn search_files(
        &self,
        query: &str,
        include_pattern: Option<&str>,
        exclude_pattern: Option<&str>,
        case_sensitive: bool,
    ) -> AppResult<Vec<String>> {
        let mut args: Vec<String> = ["--line-number", "--with-filename", "--hidden", "--no-require-git"]
            .map(str::to_string)
            .to_vec();
        if !case_sensitive {
            args.push("--ignore-case".into());
        }
        if let Some(p) = include_pattern.filter(|p| !p.is_empty()) {
            args.extend(["--glob".into(), p.to_string()]);
        }
        if let Some(p) = exclude_pattern.filter(|p| !p.is_empty()) {
            args.extend(["--glob".into(), format!("!{p}")]);
        }
        // Last, since the last matching glob wins.
        args.extend(self.protected_globs());
        args.extend(["--regexp".into(), query.to_string()]);
        args.push(self.root.to_string_lossy().into_owned());
        let out = Command::new("rg")
            .args(&args)
            .current_dir(&self.root)
            .output()
            .map_err(|e| AppError::new(format!("Ripgrep could not run: {}", oserror_repr(&e)), 500))?;
        let stdout = String::from_utf8_lossy(&out.stdout).into_owned();
        match out.status.code() {
            Some(0) => {
                let stripped = pyfmt::strip(&stdout);
                Ok(if stripped.is_empty() {
                    Vec::new()
                } else {
                    stripped.split('\n').map(str::to_string).collect()
                })
            }
            Some(1) => Ok(Vec::new()),
            code => {
                let stderr = String::from_utf8_lossy(&out.stderr).into_owned();
                tracing::error!("Ripgrep error: {stderr}");
                Err(AppError::kind(
                    ErrorKind::Ripgrep,
                    stderr,
                    code.and_then(|c| u16::try_from(c).ok()).unwrap_or(500),
                ))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn search_replace_applies_once() {
        let blocks = "<<<<<<< SEARCH\na = 1\n=======\na = 2\n>>>>>>> REPLACE\n";
        assert_eq!(process_blocks("x\na = 1\ny\n".into(), blocks).unwrap(), "x\na = 2\ny\n");
    }

    #[test]
    fn search_replace_errors() {
        let err = process_blocks("a\na\n".into(), "<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE").unwrap_err();
        assert_eq!(
            err.message,
            "Block 1: SEARCH content matches 2 locations in file: 'a'. Include more surrounding lines so it matches exactly one location."
        );
        let err = process_blocks("x".into(), "<<<<<<< SEARCH\nnope\n=======\nb\n>>>>>>> REPLACE").unwrap_err();
        assert_eq!(err.code, 404);
        let err = parse_blocks("hello\n").unwrap_err();
        assert_eq!(
            err.message,
            "Block 1 (diff line 1): unexpected text outside a block: 'hello'. Blocks must start with '<<<<<<< SEARCH'."
        );
        let err = parse_blocks("```\n```").unwrap_err();
        assert_eq!(err.message, "No SEARCH/REPLACE blocks found in diff.");
        let err = parse_blocks("<<<<<<< SEARCH\nx\n").unwrap_err();
        assert_eq!(
            err.message,
            "Block 1 (diff line 2): block is not closed with '>>>>>>> REPLACE'."
        );
        let err = parse_blocks("<<<<<<< SEARCH\n  \n=======\nx\n>>>>>>> REPLACE").unwrap_err();
        assert_eq!(err.message, "Block 1 (diff line 5): SEARCH section is empty.");
    }

    #[test]
    fn file_operations() {
        let dir = tempfile::tempdir().unwrap();
        let fs = FileSystemUtils::new(dir.path(), "backend_override.tf");
        fs.write_file("mod/main.tf", "a = 1\r\n", true).unwrap();
        assert_eq!(fs.read_file("mod/main.tf").unwrap(), "a = 1\n");
        let err = fs.write_file("script.sh", "x", true).unwrap_err();
        assert_eq!(
            err.message,
            "File extension violation. File 'script.sh' cannot be modified. Allowed extensions: ['tf', 'tfvars']"
        );
        let err = fs.read_file("missing.tf").unwrap_err();
        assert!(err.is(ErrorKind::CustomFileNotFound));
        fs.delete_file("mod/main.tf").unwrap();
        assert!(
            fs.delete_file("mod/main.tf")
                .unwrap_err()
                .is(ErrorKind::CustomFileNotFound)
        );
    }
}
