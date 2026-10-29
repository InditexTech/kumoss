// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! The one error type every layer raises.
//!
//! Mirrors the Python core's `ExceptionHandler`: a message that may reach a
//! user (or an agent) plus an HTTP-ish status code. `kind` keeps the
//! identity of the subclass for the few call sites that tell them apart.

use std::fmt;

use crate::domain::dto::ValidationResult;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ErrorKind {
    Generic,
    // application
    ReportGeneration,
    TerraformValidationFailed,
    SetLock,
    RequestFilter,
    // domain
    TemplateRendererNotFound,
    TemplateRendererArgErr,
    ToolsDefinitionEmpty,
    HistoryLastTurn,
    HistoryFirstTurn,
    ToolExecutionsExceeded,
    SentinelTool,
    UnhandledInferenceFinishReason,
    SessionConflict,
    UserNotFound,
    UserAlreadyExists,
    SessionTerminal,
    LastStatus,
    ObjectStorage,
    ObjectNotFound,
    ObjectStorageUnavailable,
    ValidationLoopExceeded,
    // infrastructure
    ToolDefinitionContextNotFound,
    ToolDefinitionNameNotFound,
    InferenceCallThinkingTool,
    InferenceCallApi,
    PhoenixPromptFetch,
    PromptSeedLoad,
    PromptSeedPush,
    TracerRootContext,
    Ripgrep,
    ToolInferenceParams,
    SearchEngine,
    TerraformRegistry,
    TerraformDocsNotFound,
    PageRead,
    PageSummary,
    PageSelection,
    Cli,
    CliTimeout,
    RepositoryUnreachable,
    InvalidIacPath,
    TokenValidation,
    TerraformBackend,
    CustomFileNotFound,
    SearchReplaceBlock,
    /// An error the Python core would have raised as a non-domain
    /// exception (KeyError, TypeError, ...): a bug or an off-contract
    /// payload rather than a modelled failure.
    Internal,
}

#[derive(Debug, Clone)]
pub struct AppError {
    pub message: String,
    pub code: u16,
    pub kind: ErrorKind,
    /// `ValidationLoopExceededError.result`: the last attempt's outcome.
    pub result: Option<Box<ValidationResult>>,
}

pub type AppResult<T> = Result<T, AppError>;

impl AppError {
    pub fn new(message: impl Into<String>, code: u16) -> Self {
        Self::kind(ErrorKind::Generic, message, code)
    }

    pub fn kind(kind: ErrorKind, message: impl Into<String>, code: u16) -> Self {
        Self {
            message: message.into(),
            code,
            kind,
            result: None,
        }
    }

    pub fn internal(message: impl Into<String>) -> Self {
        Self::kind(ErrorKind::Internal, message, 500)
    }

    /// `RepositoryUnreachable(error_code)`: the message never carries git output.
    pub fn repository_unreachable(code: u16) -> Self {
        Self::kind(
            ErrorKind::RepositoryUnreachable,
            "Repository is not reachable or access was denied.",
            code,
        )
    }

    /// Python `KeyError(key)` raised while reading a dict: `str(e)` is the
    /// quoted key.
    pub fn missing_key(key: &str) -> Self {
        Self::internal(crate::shared::pyfmt::repr_str(key))
    }

    pub fn is(&self, kind: ErrorKind) -> bool {
        self.kind == kind
    }
}

impl fmt::Display for AppError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Error {}: {}", self.code, self.message)
    }
}

impl std::error::Error for AppError {}
