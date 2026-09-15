<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# Operating modes

The Nebula web application offers four modes in the header drop-down. This guide explains what each one does today, which role it needs, what it produces, and where its limits are. It describes the current implementation; anything not yet implemented is labelled as such. If you are looking for how to phrase a request or read a report, start with the [user guide](user-guide.md) and the [FAQ](faq.md).

| Mode (UI label) | What it does today |
|---|---|
| Generate Infrastructure | Turns a natural-language request into validated Terraform code on a new branch, with a plan, a report, and optional compliance checks. |
| Partial Drift Remediation | Detects drift for the resources you describe and generates code that reconciles it. |
| Full Drift Remediation | Detects drift across the whole configuration and generates code that reconciles it. |
| Import Infrastructure | **Currently runs the apply step** of an existing session's reviewed plan. There is no end-to-end resource-import workflow in the core yet. |

Terms used below:

- **Session**: one conversation with Nebula about one repository. A session owns a Git branch named `Nebula/<UTC timestamp>` (format `Nebula/YYYY-MM-DD_HHMMSS`) and a workspace directory shared with the IaC sidecar. Each user request within the session is a **round**.
- **Operation role**: `developer` or `devops`, assigned per user and checked by the API on every IaC route. `devops` is above `developer`. These are separate from the **admin-panel roles** (`viewer`, `editor`, `admin`) that control the admin panel of the [admin portal](admin-portal.md).
- **Pinned plan**: after a successful generate round the core keeps the validated workspace, including the plan file named by `paths.session_plan_filename`, so that apply executes exactly the plan that was reviewed.
- **Session lock**: a flag on the session that blocks apply and pull-request merge until an admin-panel editor unlocks it.

## Roles at a glance

| Route | Minimum operation role | Extra condition |
|---|---|---|
| `POST /api/v1/iac/generate` | `developer` | Owner only when continuing an existing session |
| `POST /api/v1/iac/drift` | `devops` | Owner only when continuing an existing session |
| `POST /api/v1/iac/apply` | `developer` | Owner only; session not locked (`409`). A pinned plan must exist, otherwise the round that the `202` opened ends `failed` |
| `PUT /api/v1/repository/pr` (create pull request) | `developer` | Owner only |
| `PUT /api/v1/repository/pr/merge` | `developer` | Owner only; session not locked |

The web application is stricter than the API in one place: it disables Partial Drift Remediation, Full Drift Remediation, **and** Import Infrastructure for users below `devops`, showing the hint "Requires the devops operation role." The API itself accepts an apply from any `developer` who owns the session. With authentication disabled (blank `oidc.issuer_url`), the local development identity holds `devops` and sees every mode.

## Common workflow elements

**Inputs on the first request of a session.** Repository URL (without embedded credentials), the target cloud (`azure`, `gcp`, `aws`, `oci`, or `kubernetes`), a scope identifier (for example a subscription, project, or account id that appears in reports and authorization checks), an optional path to the Terraform root inside the repository, and the request text. Later requests in the same session send only the session id and the new text.

**Asynchronous execution.** Every IaC route answers `202 Accepted` with a session id immediately and runs in the background. Progress arrives through server-sent events (`GET /api/v1/events/subscribe/{session_id}`), which the web application streams; a subscription closes after roughly three hours (`orchestration.max_session_events_iteration` polls of five seconds).

**One operation per session.** The API accepts every request with `202` before the background run starts. If the session already has an operation in flight, or its last round failed, the run never starts: the core logs `Session ... already has an operation in flight.` or `Session ... is finished and cannot be resumed.` and nothing changes in the session. The web application prevents this in practice by disabling submission while a run is in progress; a failed session must be replaced by a new one.

**Statuses.** A round moves through `started`, `filtering`, `generating`, `validating`, `report`, `apply`, and ends in `completed`, `uncompleted` (the request was declined or answered without changes), or `failed`.

**Artifacts.** The core uploads artifacts to object storage under `sessions/<session>/rounds/<round>/` and the session detail view offers them as download links: code-change files, plan text, drift reports, and JSON reports. Everything is also visible to admin-panel users in the admin panel of the [admin portal](admin-portal.md).

**Pull requests.** Creating a pull request is a separate action ("Create Pull Request" in the results view). The core writes a title and description with the small model and opens the pull request from the session branch using the `GIT_TOKEN` credentials. Merging it from the web application calls the merge route, which is blocked while the session is locked.

## Generate Infrastructure

**Use case.** Create or modify Terraform code from a description: "add a private storage bucket for application logs", "open port 443 on the web security group", "rename the staging subnet".

**Minimum role.** `developer`.

**Required inputs.** Repository URL, cloud, scope id, request text; optional IaC path.

**Workflow.**

1. **Filtering.** A small-model chain with read-only workspace tools classifies the request. A change request proceeds. A question is answered in the conversation and the round ends `uncompleted`. An out-of-scope, prohibited, or ambiguous request is declined with an explanation and the round ends `uncompleted`.
2. **Prompt composition.** The compositor selects the relevant resource prompts and abbreviations for the target cloud from Phoenix, in two passes (see [Phoenix prompt templates](phoenix-prompt-templates.md)).
3. **Generate and validate loop.** The main model edits files in the workspace; changed files are uploaded as code-change artifacts and committed to the session branch. The target generator picks the Terraform targets for this round from the diff history. The IaC sidecar runs `init`, `validate`, and `plan -out session.plan` with those targets. Validation feedback is fed back to the model for up to `orchestration.max_validation_iteration` attempts (5 by default) before the round fails with `Validation loop exceeded.`
4. **Drift pre-check.** Two detect-and-reconcile iterations run on the session targets. Drift that corresponds to the session's own changes is filtered out; anything else is reconciled so that the plan reflects only intended changes.
5. **Report.** The main model turns the plan into a JSON report with a change summary (create, update, delete, recreate), detailed changes, an impact banner (`low`, `medium`, `high`), and cost estimates.
6. **Compliance check** (when `orchestration.enable_compliance_checker` is `true`). A small-model auditor checks the plan against the rules in the `general-compliance-report` prompt.
7. **Lock decision.** The session is locked when the compliance check fails or, with `orchestration.block_on_high_impact`, when the impact banner is `high`. A clean round clears an earlier lock. Notifications are sent for both conditions when the notifications sidecar is enabled.
8. **Pin.** The validated workspace, including the plan file, becomes the session's pinned plan, replacing any earlier pin.

**Inspects existing IaC and state.** Yes: the generator reads the repository, and `plan` runs against the configured backend state.

**Targets.** Generated by the target generator chain from the diff history; no manual target list is accepted.

**Artifacts and reports.** Code-change files, plan text, drift pre-check reports, a `generate` JSON report, a pushed branch, and a pull-request link once you create one.

**Plan pinned.** Yes.

**Apply, pull requests, compliance, locks.** After reviewing the report you can create a pull request, merge it, and apply. Apply and merge are refused with `409` while the lock is set; an admin-panel editor can unlock the session, or another generate round that passes cleanly clears the lock.

**Fictitious example.** Repository `https://git.example.invalid/platform/demo-iac.git`, cloud `aws`, scope `123456789012`, IaC path `envs/dev`. Request: "Create a private S3 bucket named `demo-platform-logs` with versioning and default encryption for application logs." The round produces `s3_logs.tf` on branch `Nebula/2026-09-11_101500`, a plan with one resource to create, a report with a `low` impact banner, and a passing compliance check. You create the pull request, merge it, and apply.

**Limitations.**

- Validation and plan run against the credentials in `services/iac/.env`; missing cloud credentials surface as engine errors in the session, not at startup.
- Every cloud scope needs its six guideline prompts in Phoenix; a missing one aborts the round with `Prompt not found`. See the [prompt templates guide](phoenix-prompt-templates.md#guideline-prompts-every-cloud-scope-must-provide).
- A `high` impact or a failed compliance check does not stop the round, it locks the session; review the report before asking for an unlock.

## Partial Drift Remediation

**Use case.** Someone changed resources outside Terraform (a console edit, a hotfix) and you want the code and state reconciled for a specific set of resources: "resolve the drift on the web security group".

**Minimum role.** `devops`.

**Required inputs.** Repository URL, cloud, scope id, and a **non-empty** request describing which resources to reconcile. The API rejects a partial drift request with an empty text.

**Workflow.**

1. **Filtering.** The request filter runs in drift mode: it accepts requests to resolve or scope drift and declines requests to create or modify infrastructure as an operation mismatch.
2. **Prompt composition**, as in generate.
3. **Target selection.** The target generator, in drift mode, derives Terraform targets from the request, the history, the selected resource prompts, and the `general-guidelines-targeting_policies` prompt.
4. **Detect and remediate loop**, up to `orchestration.max_drift_reports` iterations (3 by default). Each iteration runs `init`, `validate`, `plan` and `show -json` on the targets, derives the drift from the plan, stores the drift report and plan as artifacts, splits the drift into operations in groups of `orchestration.drift_group_operations` (8), and runs a generate and validate cycle per group.
5. **Report.** A `drift` JSON report with a summary, an outcome (`Succeeded`, `Partial`, `Failed`), the remediated resources, and any drift that could not be reconciled.

**Inspects existing IaC and state.** Yes; drift is computed from the plan against real state.

**Targets.** Selected by the target generator from your description.

**Artifacts and reports.** Drift reports and plans per iteration, code-change files, a `drift` JSON report, a pushed branch.

**Plan pinned.** **No.** Drift sessions do not pin a plan, so apply (and therefore the Import Infrastructure mode) on a drift-only session is accepted with `202` but its round ends `failed` with `No reviewed plan is pinned for this session; run a generate or drift round before applying.`

**Apply, pull requests, compliance, locks.** You can create a pull request from the branch. Drift rounds run no compliance audit and never set the lock. Apply is unavailable until a generate round pins a plan.

**Fictitious example.** "Resolve the drift on security group `sg-web-demo`; someone opened port 8080 in the console." Nebula plans with `-target` on that security group, detects the extra ingress rule, and generates code that restores the declared rules. You review the drift report and open a pull request.

**Limitations.**

- No compliance check, no impact banner, no lock, no pinned plan.
- Remediation is bounded by the iteration and group limits; leftover drift is reported as unreconciled.

## Full Drift Remediation

**Use case.** Reconcile the whole configuration in the IaC path, for example after a period of manual changes.

**Minimum role.** `devops`.

**Required inputs.** Repository URL, cloud, scope id, and request text. The text is required by the API, is recorded as the round's request and is given to the prompt compositor, but no filter runs on it and no targets are derived from it.

**Workflow.** Identical to partial drift except that the request filter and the target generator are skipped: the plan runs with **no targets**, covering every resource in the configuration, and the same detect and remediate loop and `drift` report follow.

**Inspects existing IaC and state.** Yes, the entire configuration.

**Targets.** None; whole workspace.

**Artifacts, plan pinning, apply, compliance, locks.** As for partial drift: artifacts and a `drift` report, no pinned plan, no compliance audit, no lock, apply unavailable until a generate round pins a plan.

**Fictitious example.** "Reconcile everything in `envs/dev`." Nebula plans the whole root, finds two drifted resources, generates the reconciling changes, and reports `Succeeded`.

**Limitations.** Large roots take longer and consume more model calls; each iteration re-plans the whole configuration.

## Import Infrastructure

**What the UI does today.** Selecting Import Infrastructure and submitting calls `POST /api/v1/iac/apply` with the current session id. No request text or targets are sent. The same apply is what the "Approve PR and Apply" button triggers after a pull request is merged. Apply:

1. Requires `developer` and session ownership and a session that is not locked; these are checked before the `202` answer.
2. Opens a new round with the text "Terraform apply.", sets the status `apply`, and checks that a pinned plan exists (otherwise the round ends `failed` with `No reviewed plan is pinned for this session`). It then runs a single `apply session.plan` job on the pinned workspace. No `init` or `plan` is re-run, so what executes is exactly the plan that was reviewed.
3. Produces an `apply` JSON report with an outcome (`Success`, `Partial`, `Failed`), an execution summary, the resource changes, and recommendations. On failure a notification of kind `iac.apply.failure` is sent when notifications are enabled. Any unexpected error in a background run of any mode marks the round `failed` and sends `system.exception.failure`.
4. Discards the pinned workspace whatever the outcome; a new generate round is needed before another apply.

**Minimum role.** The UI requires `devops` to select the mode; the API requires `developer` plus ownership.

**Required inputs.** An existing session with a pinned plan from a completed generate round. Submitting the mode from a fresh wizard with no session sends an empty session id, which the API rejects with `422`.

**Inspects existing state.** Only through the apply itself.

**Targets.** None; the pinned plan already fixes them.

**Artifacts and reports.** An `apply` JSON report and a history entry with the execution summary.

**Plan pinned.** Consumed.

**Compliance and locks.** No new compliance check; a locked session is refused with `409 Session ... is blocked; apply is not allowed.`

**What is *not* implemented.** Despite the label "Adds existing resources to manage them from the tool", the core has no route that discovers cloud resources, generates `import` blocks or runs the engine's `import` command as part of a browser-facing workflow. Related building blocks exist at a lower level:

- The IaC sidecar exposes `POST /v1/import` (runs `import <address> <resource_id>`), `POST /v1/import/state-resource-ids` (lists managed resource ids from state), and `POST /v1/import/scope-resource-ids` (lists resource ids in a cloud scope through the `az`, `gcloud`, or `aws` CLIs). See `services/iac/README.md`.
- The core's generated IaC client contains these operations, and the core defines an `import` operation type, `import` report type, and `*-terraform-import` Phoenix projects. **None of these are called or selected by any reachable core code path.**

Treat resource import as a planned capability. This guide will be updated when a core route wires the sidecar endpoints into a complete workflow.

**Fictitious example (current behaviour).** After the generate example above is merged, choose Import Infrastructure and submit. Nebula applies the pinned plan, creates the bucket, and shows an `apply` report with `Success`.

## Comparison

| | Generate Infrastructure | Partial Drift Remediation | Full Drift Remediation | Import Infrastructure (today) |
|---|---|---|---|---|
| Core route | `POST /iac/generate` | `POST /iac/drift` with `is_partial: true` | `POST /iac/drift` with `is_partial: false` | `POST /iac/apply` |
| Minimum operation role (API) | `developer` | `devops` | `devops` | `developer` + owner |
| Selectable by roles below `devops` in the UI | yes | no (shown disabled) | no (shown disabled) | no (shown disabled) |
| Request text | required, classified by the filter | required, classified by the drift filter | required by the API, not used for filtering | not sent |
| Reads existing code and state | yes | yes | yes | applies the pinned plan only |
| Terraform targets | generated from the diff history | generated from the request | none (whole root) | fixed by the pinned plan |
| Drift handling | two-iteration pre-check on session targets | up to `max_drift_reports` iterations | up to `max_drift_reports` iterations | none |
| Compliance check | yes, when enabled | no | no | no |
| Can lock the session | yes (high impact or failed compliance) | no | no | no |
| Report type | `generate` | `drift` | `drift` | `apply` |
| Pins a plan | yes | no | no | consumes it |
| Enables apply | yes | no | no | is the apply |
| Pull request | create and merge from the branch | create and merge from the branch | create and merge from the branch | typically after merge |
