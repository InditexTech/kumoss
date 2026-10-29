// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

//! `Terraform` over the IaC service (`contracts/openapi/iac.v1.yaml`).
//!
//! The service is a raw terraform executor: each POST enqueues one command
//! and the job's result is its raw `{exit_code, stdout, stderr}`. All
//! orchestration lives here, as three verbs over the plan artifact:
//!
//! * `plan` sequences `init` → `validate` → `plan -out` (init cached per
//!   instance, so retry loops initialize once) and hands back a `PlanRef`
//!   whose fingerprint is sampled right after the plan job returns;
//! * `drift` runs `show` on such a ref and parses the plan JSON into the
//!   drift summary; a ref whose fingerprint moved is re-planned first, and
//!   one naming another workspace is refused;
//! * `apply` executes the plan already in the (pinned) workspace — no init
//!   or plan at apply time.
//!
//! A non-zero exit code is a terraform-level failure reported through the
//! returned DTO; a `failed` job is a service-level fault raised as an error.
//! `init`, `plan`, `apply` and `import` carry the session's scope and
//! provider (the service injects the scope into the engine's environment);
//! `validate` and `show` reach no cloud API and go unscoped. An OCI plan is
//! followed by a `show` of its artifact, since a compartment is a resource
//! argument and a hardcoded one would escape the scope.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant, SystemTime};

use async_trait::async_trait;
use serde_json::{Value, json};
use uuid::Uuid;

use crate::domain::dto::{
    TerraformApplyDto, TerraformDiscoveryDto, TerraformDriftDto, TerraformImportResourceDto, TerraformPlanDto,
};
use crate::domain::ports::{Git, Terraform};
use crate::domain::value_objects::PlanRef;
use crate::infrastructure::external::contract::{CallError, ContractResponse, Problem, call};
use crate::infrastructure::telemetry;
use crate::infrastructure::terraform::backend::TerraformBackend;
use crate::infrastructure::terraform::utils;
use crate::shared::config::SystemConfig;
use crate::shared::constants::TerraformProvider;
use crate::shared::error::{AppError, AppResult};
use crate::shared::pyfmt;

/// A finished command.
#[derive(Debug, Clone)]
struct OpResult {
    exit_code: i64,
    stdout: String,
    stderr: String,
}

fn or_default(s: &str, default: &str) -> String {
    if s.is_empty() {
        default.to_string()
    } else {
        s.to_string()
    }
}

fn transport(e: CallError) -> AppError {
    match e {
        CallError::Timeout(m) => AppError::new(format!("IaC service timed out: {m}"), 504),
        CallError::Request(m) => AppError::new(format!("IaC service unreachable: {m}"), 502),
    }
}

/// `json.loads` failure text, as Python printed it.
fn json_error(e: &serde_json::Error) -> String {
    format!(
        "Expecting value: line {} column {} (char {})",
        e.line(),
        e.column(),
        e.column().saturating_sub(1)
    )
}

pub struct IacTerraform {
    workspace_path: PathBuf,
    git: Arc<dyn Git>,
    scope_id: String,
    provider: TerraformProvider,
    backend: TerraformBackend,
    initialized: AtomicBool,
    cfg: &'static SystemConfig,
}

impl IacTerraform {
    pub fn new(
        workspace_path: PathBuf,
        git: Arc<dyn Git>,
        scope_id: String,
        provider: TerraformProvider,
        backend: TerraformBackend,
        cfg: &'static SystemConfig,
    ) -> Self {
        Self {
            workspace_path,
            git,
            scope_id,
            provider,
            backend,
            initialized: AtomicBool::new(false),
            cfg,
        }
    }

    fn posix(path: &Path) -> String {
        path.to_string_lossy().into_owned()
    }

    async fn submit(&self, path: &str, body: &Value) -> AppResult<ContractResponse> {
        let svc = &self.cfg.services.iac;
        call(
            reqwest::Method::POST,
            &svc.endpoint,
            &svc.token(),
            svc.timeout,
            path,
            Some(body),
        )
        .await
        .map_err(transport)
    }

    /// Submit one operation and poll it to completion; a rejected
    /// submission, a `failed` job or an unexpected result shape is a
    /// service-level fault.
    async fn run_op(&self, op_name: &str, path: &str, body: &Value) -> AppResult<OpResult> {
        let resp = self.submit(path, body).await?;
        let job_id = if resp.status == 202 {
            resp.json()
                .ok()
                .and_then(|v| v.get("job_id").and_then(Value::as_str).map(str::to_string))
                .and_then(|s| Uuid::parse_str(&s).ok())
        } else {
            None
        };
        let Some(job_id) = job_id else {
            let parsed = if resp.status == 202 {
                "<unparseable JobAccepted>".to_string()
            } else {
                crate::infrastructure::external::contract::unexpected_repr(&resp, &[401, 403, 404, 422, 503])
            };
            return Err(AppError::new(
                format!("IaC service did not accept the {op_name} job: {parsed}"),
                502,
            ));
        };
        let job = self.poll_job(&job_id).await?;
        let status = job.get("status").and_then(Value::as_str).unwrap_or("");
        if status == "failed" {
            let error_text = match job.get("error") {
                Some(e) if e.is_object() => match Problem::from_value(e) {
                    Ok(p) => match p.detail.filter(|d| !d.is_empty()) {
                        Some(d) => format!("{}: {d}", p.title),
                        None => p.title,
                    },
                    Err(_) => pyfmt::repr_value(e),
                },
                Some(other) => pyfmt::repr_value(other),
                None => "None".into(),
            };
            return Err(AppError::new(
                format!("IaC {op_name} job failed on the service: {error_text}"),
                502,
            ));
        }
        let result = job.get("result").cloned().unwrap_or(Value::Null);
        let parsed = (|| {
            Some(OpResult {
                exit_code: result.get("exit_code")?.as_i64()?,
                stdout: result.get("stdout")?.as_str()?.to_string(),
                stderr: result.get("stderr")?.as_str()?.to_string(),
            })
        })();
        parsed.ok_or_else(|| {
            AppError::new(
                format!(
                    "IaC service returned an unexpected job result: {}",
                    pyfmt::repr_value(&result)
                ),
                502,
            )
        })
    }

    /// Poll `GET /v1/jobs/{job_id}` until terminal; `job_timeout` bounds the
    /// total wait (queue + command). A non-Job answer means the job is gone
    /// and will never finish.
    async fn poll_job(&self, job_id: &Uuid) -> AppResult<Value> {
        let svc = &self.cfg.services.iac;
        let deadline = Instant::now() + Duration::from_secs_f64(svc.job_timeout);
        let path = format!("/v1/jobs/{job_id}");
        loop {
            let resp = match call(
                reqwest::Method::GET,
                &svc.endpoint,
                &svc.token(),
                svc.timeout,
                &path,
                None,
            )
            .await
            {
                Ok(r) => r,
                // httpx.RemoteProtocolError (the connection dropped mid-way) is retried once.
                Err(CallError::Request(m)) if m.contains("connection closed") || m.contains("IncompleteMessage") => {
                    call(
                        reqwest::Method::GET,
                        &svc.endpoint,
                        &svc.token(),
                        svc.timeout,
                        &path,
                        None,
                    )
                    .await
                    .map_err(transport)?
                }
                Err(e) => return Err(transport(e)),
            };
            let job = if resp.status == 200 {
                resp.json()
                    .ok()
                    .filter(|j| j.get("status").and_then(Value::as_str).is_some())
            } else {
                None
            };
            let Some(job) = job else {
                let repr = crate::infrastructure::external::contract::unexpected_repr(&resp, &[401, 404, 422]);
                return Err(AppError::new(
                    format!("IaC service lost or rejected job {job_id}: {repr}"),
                    502,
                ));
            };
            let status = job["status"].as_str().unwrap_or("").to_string();
            if status == "succeeded" || status == "failed" {
                return Ok(job);
            }
            if Instant::now() >= deadline {
                return Err(AppError::new(
                    format!(
                        "IaC job {job_id} did not finish within {:.0}s (last status: {status}).",
                        svc.job_timeout
                    ),
                    504,
                ));
            }
            tokio::time::sleep(Duration::from_secs_f64(svc.job_poll_interval)).await;
        }
    }

    /// Initialize unless this instance already did: `None` once initialized,
    /// or the failing result (the flag stays unset so the next call retries).
    async fn ensure_init(&self) -> AppResult<Option<OpResult>> {
        if self.initialized.load(Ordering::SeqCst) {
            return Ok(None);
        }
        if !self.cfg.storage.state_bucket().is_empty() {
            self.backend.apply(&self.workspace_path)?;
        }
        let res = self
            .run_op(
                "init",
                "/v1/init",
                &json!({
                    "workspace_path": Self::posix(&self.workspace_path),
                    "scope_id": self.scope_id,
                    "terraform_provider": self.provider.value(),
                }),
            )
            .await?;
        if res.exit_code != 0 {
            return Ok(Some(res));
        }
        self.initialized.store(true, Ordering::SeqCst);
        Ok(None)
    }

    fn needs_init(res: &OpResult) -> bool {
        format!("{}\n{}", res.stderr, res.stdout)
            .to_lowercase()
            .contains("terraform init")
    }

    /// Run an op that needs an initialized workspace, re-initializing once:
    /// the generation loop may add a provider or module between iterations,
    /// after which terraform asks for `terraform init`.
    async fn run_initialized_op(&self, op_name: &str, path: &str, body: &Value) -> AppResult<OpResult> {
        let res = self.run_op(op_name, path, body).await?;
        if res.exit_code == 0 || !Self::needs_init(&res) {
            return Ok(res);
        }
        self.initialized.store(false, Ordering::SeqCst);
        if let Some(init_res) = self.ensure_init().await? {
            return Ok(init_res);
        }
        self.run_op(op_name, path, body).await
    }

    async fn plan_impl(&self, targets: &[String]) -> AppResult<TerraformPlanDto> {
        let failed = |feedback: String, stdout: String| TerraformPlanDto {
            ok: false,
            feedback,
            stdout,
            targets: targets.to_vec(),
            plan: None,
        };
        if let Some(init) = self.ensure_init().await? {
            return Ok(failed(or_default(&init.stderr, "terraform init failed"), String::new()));
        }
        let validate = self
            .run_initialized_op(
                "validate",
                "/v1/validate",
                &json!({"workspace_path": Self::posix(&self.workspace_path)}),
            )
            .await?;
        if validate.exit_code != 0 {
            return Ok(failed(
                or_default(&validate.stderr, "terraform validate failed"),
                String::new(),
            ));
        }
        let plan_file = &self.cfg.paths.session_plan_filename;
        let plan = self
            .run_initialized_op(
                "plan",
                "/v1/plan",
                &json!({
                    "workspace_path": Self::posix(&self.workspace_path),
                    "scope_id": self.scope_id,
                    "terraform_provider": self.provider.value(),
                    "plan_file": plan_file,
                    "targets": targets,
                }),
            )
            .await?;
        // FIXME: ad hoc OCI workaround - AWS, GCP and OCI don't bind the scope
        // id to the terraform scope the way Azure does (an env variable).
        let scope_feedback = if plan.exit_code == 0 && self.provider == TerraformProvider::Oci {
            self.oci_scope_feedback().await?
        } else {
            String::new()
        };
        if plan.exit_code != 0 {
            return Ok(failed(or_default(&plan.stderr, "terraform plan failed"), plan.stdout));
        }
        if !scope_feedback.is_empty() {
            return Ok(failed(scope_feedback, plan.stdout));
        }
        Ok(TerraformPlanDto {
            ok: true,
            feedback: String::new(),
            stdout: plan.stdout.clone(),
            targets: targets.to_vec(),
            plan: Some(PlanRef {
                workspace: self.workspace_path.clone(),
                plan_file: plan_file.clone(),
                targets: targets.to_vec(),
                commit: self.git.get_workspace_revision().await?,
                stdout: plan.stdout,
            }),
        })
    }

    /// `plan` traced with the keyword arguments it was called with.
    async fn plan_traced(&self, targets: &[String], input: Value) -> AppResult<TerraformPlanDto> {
        let start = SystemTime::now();
        let out = self.plan_impl(targets).await?;
        telemetry::trace_terraform(start, "plan", out.ok, out.summary(), input);
        Ok(out)
    }

    /// Feedback naming the resources the session plan creates outside the
    /// request's compartment, or "" when there are none.
    async fn oci_scope_feedback(&self) -> AppResult<String> {
        let show = self
            .run_initialized_op(
                "show",
                "/v1/show",
                &json!({
                    "workspace_path": Self::posix(&self.workspace_path),
                    "plan_file": self.cfg.paths.session_plan_filename,
                }),
            )
            .await?;
        if show.exit_code != 0 {
            return Ok(or_default(&show.stderr, "terraform show failed"));
        }
        let plan_json: Value = serde_json::from_str(&show.stdout).map_err(|e| {
            AppError::new(
                format!(
                    "terraform show succeeded but returned unparseable JSON: {}",
                    json_error(&e)
                ),
                502,
            )
        })?;
        let outside = utils::oci_creations_outside(&plan_json, &self.scope_id);
        if outside.is_empty() {
            return Ok(String::new());
        }
        Ok(format!(
            "These resources would be created outside the request's compartment ({}): {}. Set their compartment_id to var.compartment_ocid, or to a compartment this configuration creates under it; never hardcode a compartment OCID.",
            self.scope_id,
            outside.join(", ")
        ))
    }

    async fn drift_impl(&self, plan: &PlanRef) -> AppResult<TerraformDriftDto> {
        if plan.workspace != self.workspace_path {
            return Err(AppError::new(
                format!(
                    "Plan {} belongs to another workspace than {}",
                    plan.py_repr(),
                    Self::posix(&self.workspace_path)
                ),
                500,
            ));
        }
        let mut plan = plan.clone();
        if self.git.get_workspace_revision().await? != plan.commit {
            tracing::warn!("Workspace changed since the plan; re-planning before reading drift");
            let res = self.plan_traced(&plan.targets, json!({})).await?;
            match res.plan {
                None => {
                    return Ok(TerraformDriftDto {
                        in_sync: false,
                        drift: String::new(),
                        feedback: res.feedback,
                        stdout: res.stdout,
                        plan: None,
                        excluded: Vec::new(),
                    });
                }
                Some(p) => plan = p,
            }
        }
        let failed = |feedback: String, stdout: String| TerraformDriftDto {
            in_sync: false,
            drift: String::new(),
            feedback,
            stdout,
            plan: None,
            excluded: Vec::new(),
        };
        if let Some(init) = self.ensure_init().await? {
            return Ok(failed(
                or_default(&init.stderr, "terraform init failed"),
                plan.stdout.clone(),
            ));
        }
        let show = self
            .run_initialized_op(
                "show",
                "/v1/show",
                &json!({"workspace_path": Self::posix(&plan.workspace), "plan_file": plan.plan_file}),
            )
            .await?;
        if show.exit_code != 0 {
            return Ok(failed(
                or_default(&show.stderr, "terraform show failed"),
                plan.stdout.clone(),
            ));
        }
        let plan_json: Value = serde_json::from_str(&show.stdout).map_err(|e| {
            AppError::new(
                format!(
                    "terraform show succeeded but returned unparseable JSON: {}",
                    json_error(&e)
                ),
                502,
            )
        })?;
        let drift = utils::plan_to_drift(&plan_json, true)?;
        Ok(TerraformDriftDto {
            in_sync: drift.is_empty(),
            drift: if drift.is_empty() {
                String::new()
            } else {
                pyfmt::json_dumps(&Value::Array(drift))
            },
            feedback: String::new(),
            stdout: plan.stdout.clone(),
            plan: Some(plan),
            excluded: Vec::new(),
        })
    }

    async fn discovery(
        &self,
        op_name: &str,
        path: &str,
        body: Value,
        tolerate_failure: bool,
    ) -> AppResult<TerraformDiscoveryDto> {
        if let Some(init) = self.ensure_init().await? {
            return Err(AppError::new(
                format!("terraform init failed: {}", or_default(&init.stderr, "unknown error")),
                502,
            ));
        }
        let res = self.run_initialized_op(op_name, path, &body).await?;
        if res.exit_code != 0 {
            if tolerate_failure {
                return Ok(TerraformDiscoveryDto {
                    resource_ids: Vec::new(),
                    feedback: or_default(&res.stderr, "unknown error"),
                    excluded: Vec::new(),
                });
            }
            return Err(AppError::new(
                format!(
                    "terraform state pull failed: {}",
                    or_default(&res.stderr, "unknown error")
                ),
                502,
            ));
        }
        let what = if tolerate_failure { "scope" } else { "state" };
        let ids: Value = serde_json::from_str(&res.stdout).map_err(|e| {
            AppError::new(
                format!("IaC service returned invalid {what} resource IDs: {}", json_error(&e)),
                502,
            )
        })?;
        let ids = ids
            .as_array()
            .and_then(|a| {
                a.iter()
                    .map(|v| v.as_str().map(str::to_string))
                    .collect::<Option<Vec<_>>>()
            })
            .ok_or_else(|| AppError::new(format!("IaC service returned invalid {what} resource IDs."), 502))?;
        Ok(TerraformDiscoveryDto {
            resource_ids: ids,
            feedback: String::new(),
            excluded: Vec::new(),
        })
    }
}

#[async_trait]
impl Terraform for IacTerraform {
    async fn plan(&self, targets: &[String]) -> AppResult<TerraformPlanDto> {
        self.plan_traced(targets, json!({"targets": targets})).await
    }

    async fn drift(&self, plan: &PlanRef) -> AppResult<TerraformDriftDto> {
        let start = SystemTime::now();
        let out = self.drift_impl(plan).await?;
        telemetry::trace_terraform(start, "drift", out.ok(), out.summary(), json!({"plan": plan.py_repr()}));
        Ok(out)
    }

    async fn apply(&self) -> AppResult<TerraformApplyDto> {
        let start = SystemTime::now();
        let res = self
            .run_op(
                "apply",
                "/v1/apply",
                &json!({
                    "workspace_path": Self::posix(&self.workspace_path),
                    "scope_id": self.scope_id,
                    "terraform_provider": self.provider.value(),
                    "plan_file": self.cfg.paths.session_plan_filename,
                }),
            )
            .await?;
        let out = if res.exit_code != 0 {
            TerraformApplyDto {
                ok: false,
                stdout: res.stdout,
                feedback: or_default(&res.stderr, "terraform apply failed"),
            }
        } else {
            TerraformApplyDto {
                ok: true,
                stdout: res.stdout,
                feedback: String::new(),
            }
        };
        telemetry::trace_terraform(start, "apply", out.ok, out.summary(), json!({}));
        Ok(out)
    }

    async fn state_resource_ids(&self) -> AppResult<TerraformDiscoveryDto> {
        let start = SystemTime::now();
        let out = self
            .discovery(
                "state_resource_ids",
                "/v1/import/state-resource-ids",
                json!({"workspace_path": Self::posix(&self.workspace_path)}),
                false,
            )
            .await?;
        telemetry::trace_terraform(start, "state_resource_ids", out.ok(), &out.summary(), json!({}));
        Ok(out)
    }

    async fn scope_resource_ids(
        &self,
        scope_id: &str,
        terraform_provider: TerraformProvider,
    ) -> AppResult<TerraformDiscoveryDto> {
        let start = SystemTime::now();
        let out = self
            .discovery(
                "scope_resource_ids",
                "/v1/import/scope-resource-ids",
                json!({
                    "workspace_path": Self::posix(&self.workspace_path),
                    "scope_id": scope_id,
                    "terraform_provider": terraform_provider.value(),
                }),
                true,
            )
            .await?;
        telemetry::trace_terraform(
            start,
            "scope_resource_ids",
            out.ok(),
            &out.summary(),
            json!({"scope_id": scope_id, "terraform_provider": format!("TerraformProvider.{}", terraform_provider.name())}),
        );
        Ok(out)
    }

    async fn import_resource(&self, address: &str, resource_id: &str) -> AppResult<TerraformImportResourceDto> {
        let start = SystemTime::now();
        if let Some(init) = self.ensure_init().await? {
            return Err(AppError::new(
                format!("terraform init failed: {}", or_default(&init.stderr, "unknown error")),
                502,
            ));
        }
        let res = self
            .run_initialized_op(
                "import_resource",
                "/v1/import",
                &json!({
                    "workspace_path": Self::posix(&self.workspace_path),
                    "scope_id": self.scope_id,
                    "terraform_provider": self.provider.value(),
                    "address": address,
                    "resource_id": resource_id,
                }),
            )
            .await?;
        let out = if res.exit_code != 0 {
            TerraformImportResourceDto {
                ok: false,
                stdout: res.stdout,
                feedback: or_default(&res.stderr, "terraform import failed"),
            }
        } else {
            TerraformImportResourceDto {
                ok: true,
                stdout: res.stdout,
                feedback: String::new(),
            }
        };
        telemetry::trace_terraform(
            start,
            "import_resource",
            out.ok,
            out.summary(),
            json!({"address": address, "resource_id": resource_id}),
        );
        Ok(out)
    }
}
