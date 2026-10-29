// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! Builds the service graph of one session run.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use crate::application::drift_import::{TerraformDriftService, TerraformImportService};
use crate::application::services::{PullRequestService, ReportService, RequestsFilterService};
use crate::application::state::AppState;
use crate::application::use_cases::{
    TerraformApplyHandler, TerraformCrudHandler, TerraformDriftHandler, TerraformImportHandler,
};
use crate::domain::entities::{SessionContext, SharedSession};
use crate::domain::ports::{FileSystem, Git, LlmProvider, Terraform};
use crate::domain::services::artifact_storage::ArtifactStorageService;
use crate::domain::services::llm::LlmOrchestrationService;
use crate::domain::services::session::SessionService;
use crate::domain::services::targets::{TerraformImportAddressService, TerraformTargetService};
use crate::domain::services::task::TaskService;
use crate::domain::services::template::TemplateOrchestrationService;
use crate::domain::services::tools::ToolOrchestrationService;
use crate::domain::services::validation::{ComplianceCheckService, TerraformValidationService};
use crate::infrastructure::external::summarizer::SearchResultsSummarizer;
use crate::infrastructure::filesystem::fs::FileSystemUtils;
use crate::infrastructure::filesystem::git::GitUtils;
use crate::infrastructure::filesystem::iac_root::IacRootDetector;
use crate::infrastructure::llm::adapter::SidecarLlm;
use crate::infrastructure::templates::adapter::TemplateAdapter;
use crate::infrastructure::terraform::backend::TerraformBackend;
use crate::infrastructure::terraform::iac::IacTerraform;
use crate::infrastructure::terraform::utils::project_id;
use crate::infrastructure::tools::ToolRegistryImpl;
use crate::shared::error::AppResult;

/// The per-session building blocks every handler shares.
struct Core {
    files: Arc<dyn FileSystem>,
    git: Arc<dyn Git>,
    artifacts: ArtifactStorageService,
    tools: ToolOrchestrationService,
    llm: LlmOrchestrationService,
    templates: TemplateOrchestrationService,
    session: SessionService,
}

pub struct ApplicationFactory<'a> {
    state: &'a AppState,
    ctx: SharedSession,
}

impl<'a> ApplicationFactory<'a> {
    pub fn new(state: &'a AppState, ctx: SharedSession) -> Self {
        Self { state, ctx }
    }

    pub fn git_utils(state: &AppState, repo_uri: &str, path: Option<&Path>) -> GitUtils {
        GitUtils::new(repo_uri, path, state.cfg)
    }

    pub fn llm_adapter(state: &AppState, model: &str, max_tokens: i64, temperature: f64) -> Arc<dyn LlmProvider> {
        Arc::new(SidecarLlm::new(
            model,
            temperature,
            max_tokens,
            state.cfg.llm.timeout,
            state.sidecar.clone(),
        ))
    }

    pub fn iac_root_detector(state: &AppState) -> IacRootDetector {
        IacRootDetector::new(state.cfg)
    }

    fn template_adapter(&self, cwd: &Path) -> TemplateAdapter {
        let provider = self.ctx.read(|c| c.terraform_prv);
        TemplateAdapter::new(
            provider,
            &cwd.to_string_lossy(),
            &self.state.cfg.environment,
            self.state.fetcher.clone(),
        )
    }

    fn search_summarizer(&self, cwd: &Path) -> AppResult<SearchResultsSummarizer> {
        let cfg = self.state.cfg;
        let templates = self.template_adapter(cwd);
        Ok(SearchResultsSummarizer::new(
            Self::llm_adapter(self.state, &cfg.llm.small_model, cfg.llm.max_output_tokens, 0.5),
            templates.render_search_summarizer(SearchResultsSummarizer::irrelevant_marker())?,
            templates.render_search_selector()?,
            cfg,
        ))
    }

    fn default_llm(&self, tools: Option<ToolOrchestrationService>) -> LlmOrchestrationService {
        let cfg = self.state.cfg;
        LlmOrchestrationService::new(
            Self::llm_adapter(
                self.state,
                &cfg.llm.model,
                cfg.llm.max_output_tokens,
                cfg.llm.temperature,
            ),
            Self::llm_adapter(
                self.state,
                &cfg.llm.small_model,
                cfg.llm.max_output_tokens,
                cfg.llm.temperature,
            ),
            tools,
            cfg,
        )
    }

    fn templates(
        &self,
        cwd: &Path,
        llm: &LlmOrchestrationService,
        tools: &ToolOrchestrationService,
    ) -> TemplateOrchestrationService {
        TemplateOrchestrationService::new(self.template_adapter(cwd), llm.clone(), tools.clone())
    }

    fn terraform(&self, project_root: &Path) -> Arc<dyn Terraform> {
        let (repo_uri, scope_id, iac_path, provider) = self.ctx.read(|c| {
            (
                c.repo_uri.clone(),
                c.scope_id.clone(),
                c.iac_path.clone(),
                c.terraform_prv,
            )
        });
        // The git that fingerprints the workspace is rooted at the same tree
        // as the terraform service by construction.
        let git: Arc<dyn Git> = Arc::new(Self::git_utils(self.state, &repo_uri, Some(project_root)));
        let pid = project_id(&repo_uri, &scope_id, iac_path.as_deref());
        Arc::new(IacTerraform::new(
            project_root.to_path_buf(),
            git,
            scope_id,
            provider,
            TerraformBackend::new(pid, self.state.cfg),
            self.state.cfg,
        ))
    }

    fn core(&self) -> AppResult<Core> {
        let state = self.state;
        let call_dir = self.ctx.read(|c| c.call_dir());
        let files_impl = FileSystemUtils::new(&call_dir, &state.cfg.paths.backend_override_filename);
        let project_root = files_impl.project_root();
        let files: Arc<dyn FileSystem> = Arc::new(files_impl);
        let repo_uri = self.ctx.read(|c| c.repo_uri.clone());
        let git: Arc<dyn Git> = Arc::new(Self::git_utils(state, &repo_uri, Some(&project_root)));
        let artifacts = ArtifactStorageService::new(state.storage.clone(), state.db.clone());
        let registry = ToolRegistryImpl::new_workspace(
            state.cfg,
            files.clone(),
            git.clone(),
            self.search_summarizer(&call_dir)?,
            state.sidecar.clone(),
        );
        let tools = ToolOrchestrationService::new(Arc::new(registry));
        let llm = self.default_llm(Some(tools.clone()));
        let templates = self.templates(&project_root, &llm, &tools);
        let session = SessionService::new(llm.clone(), self.ctx.clone(), templates.clone(), state.db.clone());
        Ok(Core {
            files,
            git,
            artifacts,
            tools,
            llm,
            templates,
            session,
        })
    }

    fn validation(&self, core: &Core) -> TerraformValidationService {
        TerraformValidationService::new(
            core.git.clone(),
            core.files.clone(),
            core.session.clone(),
            core.templates.clone(),
            core.llm.clone(),
            core.tools.clone(),
            core.artifacts.clone(),
        )
    }

    fn report(&self, core: &Core) -> ReportService {
        ReportService::new(
            core.llm.clone(),
            core.tools.clone(),
            core.templates.clone(),
            core.session.clone(),
            core.artifacts.clone(),
        )
    }

    fn requests_filter(&self, core: &Core) -> RequestsFilterService {
        RequestsFilterService::new(
            core.session.clone(),
            core.llm.clone(),
            core.tools.clone(),
            core.templates.clone(),
        )
    }

    fn task(&self, core: &Core) -> TaskService {
        TaskService::new(
            core.llm.clone(),
            core.templates.clone(),
            core.tools.clone(),
            self.state.cfg,
        )
    }

    fn targets(&self, core: &Core) -> TerraformTargetService {
        TerraformTargetService::new(core.tools.clone(), core.llm.clone(), core.templates.clone())
    }

    fn drift(&self, core: &Core, terraform: Arc<dyn Terraform>) -> TerraformDriftService {
        TerraformDriftService::new(
            self.ctx.clone(),
            core.session.clone(),
            self.validation(core),
            terraform,
            self.task(core),
            core.artifacts.clone(),
            self.state.cfg,
        )
    }

    fn compliance(&self, core: &Core) -> ComplianceCheckService {
        ComplianceCheckService::new(
            core.tools.clone(),
            core.llm.clone(),
            core.templates.clone(),
            core.artifacts.clone(),
            self.state.cfg,
        )
    }

    fn project_root(&self) -> PathBuf {
        let call_dir = self.ctx.read(|c| c.call_dir());
        FileSystemUtils::new(&call_dir, &self.state.cfg.paths.backend_override_filename).project_root()
    }

    pub fn terraform_crud_handler(&self) -> AppResult<TerraformCrudHandler> {
        let core = self.core()?;
        let terraform = self.terraform(&self.project_root());
        Ok(TerraformCrudHandler {
            ctx: self.ctx.clone(),
            session: core.session.clone(),
            terraform: terraform.clone(),
            validation: self.validation(&core),
            templates: core.templates.clone(),
            requests_filter: self.requests_filter(&core),
            report: self.report(&core),
            targets: self.targets(&core),
            drift: self.drift(&core, terraform),
            compliance: self.compliance(&core),
            workspace: self.state.workspace.clone(),
            db: self.state.db.clone(),
            notifications: self.state.notifications.clone(),
            cfg: self.state.cfg,
        })
    }

    pub fn terraform_drift_handler(&self) -> AppResult<TerraformDriftHandler> {
        let core = self.core()?;
        let terraform = self.terraform(&self.project_root());
        Ok(TerraformDriftHandler {
            ctx: self.ctx.clone(),
            session: core.session.clone(),
            templates: core.templates.clone(),
            requests_filter: self.requests_filter(&core),
            report: self.report(&core),
            targets: self.targets(&core),
            drift: self.drift(&core, terraform),
            cfg: self.state.cfg,
        })
    }

    pub fn terraform_apply_handler(&self) -> AppResult<TerraformApplyHandler> {
        let core = self.core()?;
        let id = self.ctx.id();
        let terraform = self.terraform(&self.state.workspace.pinned_dir(&id));
        Ok(TerraformApplyHandler {
            ctx: self.ctx.clone(),
            terraform,
            session: core.session.clone(),
            report: self.report(&core),
            templates: core.templates.clone(),
            compliance: self.compliance(&core),
            workspace: self.state.workspace.clone(),
            notifications: self.state.notifications.clone(),
        })
    }

    pub fn terraform_import_handler(&self) -> AppResult<TerraformImportHandler> {
        let core = self.core()?;
        let terraform = self.terraform(&self.project_root());
        Ok(TerraformImportHandler {
            ctx: self.ctx.clone(),
            session: core.session.clone(),
            terraform: terraform.clone(),
            validation: self.validation(&core),
            templates: core.templates.clone(),
            requests_filter: self.requests_filter(&core),
            import: TerraformImportService::new(terraform.clone(), core.templates.clone()),
            import_address: TerraformImportAddressService::new(
                core.tools.clone(),
                core.llm.clone(),
                core.templates.clone(),
            ),
            targets: self.targets(&core),
            drift: self.drift(&core, terraform),
            report: self.report(&core),
            task: self.task(&core),
            cfg: self.state.cfg,
        })
    }

    /// The pull-request service works outside any workspace: git at the
    /// upload folder and the static tool registry.
    pub fn pull_request_service(state: &'a AppState, ctx: SessionContext) -> AppResult<PullRequestService> {
        let upload = state.cfg.paths.upload_folder.clone();
        let factory = Self::new(state, SharedSession::new(ctx.clone()));
        let git: Arc<dyn Git> = Arc::new(Self::git_utils(state, &ctx.repo_uri, None));
        // The Python core built this summarizer on `ctx.call_dir`, which is
        // never set here (an AssertionError on every call); the search
        // templates do not use the working directory.
        let registry =
            ToolRegistryImpl::new_static(state.cfg, factory.search_summarizer(&upload)?, state.sidecar.clone());
        let tools = ToolOrchestrationService::new(Arc::new(registry));
        let llm = factory.default_llm(Some(tools.clone()));
        let templates = factory.templates(&upload, &llm, &tools);
        Ok(PullRequestService::new(
            ctx,
            git,
            llm,
            tools,
            templates,
            state.db.clone(),
        ))
    }
}
