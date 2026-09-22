<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# User guide

This guide is for people who use the Nebula web application to change infrastructure: how to make a request, how to phrase it so it is accepted, how to follow the session, how to read the results, what a lock means, how to open and merge the pull request and apply, and how to get help. It describes what the application does today. Quick answers are in the [FAQ](faq.md); the exact behaviour of each mode is in [Operating modes](modes.md).

## 1. Before you start

You need:

- **An account.** Your administrator gives you access through your organization's identity provider. On first login you have the `developer` role, which lets you generate infrastructure, open and merge pull requests, and apply your own sessions. Drift remediation needs the `devops` role; ask your administrator ([Admin portal](admin-portal.md)).
- **A repository URL** that holds Terraform-compatible code and that Nebula's service account can clone and push to. Enter the plain URL; URLs with a user name or token embedded are rejected.
- **The cloud scope** your change targets: the Azure subscription id, Google Cloud project id, AWS account id, or OCI compartment OCID. Kubernetes has no cloud scope of its own — the API asks for "any stable identifier", so use whatever your team agreed on (a cluster or namespace name works).

Nebula never asks you for cloud or Git credentials. It uses the identity your platform team configured.

## 2. Concepts in one minute

| Term | Meaning |
|---|---|
| **Mode** | What you want done, chosen in the header drop-down: Generate Infrastructure, Partial Drift Remediation, Full Drift Remediation, Import Infrastructure. |
| **Session** | One conversation about one repository. It owns a Git branch named `Nebula/<date_time>` where all changes are pushed. |
| **Round** | One request within a session. Follow-up requests add rounds to the same session and branch. |
| **Plan** | The engine's preview of what would change in the cloud. Nebula validates and plans your code before showing results. |
| **Report** | Nebula's readable summary of the plan: what is created, updated, deleted, or recreated, the potential impact, and an estimated cost. |
| **Lock** | A flag that blocks merging the pull request and applying until a reviewer releases it. Set automatically for high-impact or non-compliant changes. |
| **Pull request** | Opened on demand from the session branch so your team can review the code with your usual process. |
| **Apply** | Executes exactly the reviewed plan in the cloud. Always a human action, never automatic. |

## 3. Making a request

1. **Choose the mode** in the header drop-down. Most work uses *Generate Infrastructure*. The drift modes and *Import Infrastructure* are shown greyed out with the hint "Requires the devops operation role." if you do not hold that role.
2. **"What do you need?"** Type your request (up to 500 characters) and press Enter. The rotating hints under the field show the expected level of detail, for example "Deploy a PostgreSQL database on Azure" or "Create a virtual network with three subnets".
3. **"What is the repository URL?"** Paste the repository URL. Nebula resolves it, clones only its metadata, and looks for Terraform roots among the files committed on the default branch: directories that hold `.tf` files, skipping `modules`, `examples`, and `.terraform` folders, and keeping those with a `main.tf`-style marker or a `.tfvars` file (the exact rules and examples are in [Operating modes](modes.md#how-nebula-finds-terraform-roots)). This is the step that takes a few seconds ("Resolving repository...").
4. **"Which IaC path?"** If the repository has more than one Terraform root, pick the directory to work in. With exactly one root this step is skipped. If none is found you see "No IaC paths found in this repository. Please check the repository and try again." — usually because the `.tf` files are not committed on the default branch or live under a `modules` or `examples` directory. Top-level `.tf` files are offered as the path `.`.
5. **"Which cloud provider?"** Pick Microsoft Azure, Google Cloud, Amazon Web Services, Oracle Cloud Infrastructure, or Kubernetes.
6. **Cloud scope.** Enter the subscription id, project id, account id, or compartment OCID — for Kubernetes, any stable identifier your team uses. Only letters, digits, and hyphens are accepted (up to 64 characters); the field does not advance until the value is valid.
7. **Permissions check.** Nebula asks your organization's authorization service whether you may work there, sending the cloud, the repository URL, and the IaC path — not the scope you just typed ("Checking permissions on ..."). If the answer is no, the reason is shown with two buttons: *Try again* (back to the scope) and *Start over*. In a deployment that has not connected such a service, which is the shipped default, the answer is always yes and the step passes straight through.

The session then starts and you are taken to the progress screen.

**Errors at this stage.** The wizard always shows the fixed message "Could not resolve repository. Please try again." when the reachability check fails, whatever the underlying cause. It runs before the session is created — Nebula answers an error and nothing is started. The more specific reason — the Git client's own text, or "Cannot reach repository: <url>" when the client said nothing — is the API response's `detail` field: visible to direct API callers, and to the wizard itself only if a later request (for example the first generate step) fails with a 400, in which case the UI falls back to showing that `detail`. Check that the URL is reachable and that Nebula's service account has access. A repository that becomes unreachable later, when the session clones it for real, is a different failure: the round ends with "git clone failed: ..." and the session is failed and cannot be resumed.

## 4. Writing a request that gets accepted

Every request is first read by a filter that decides whether it is an infrastructure change Nebula can make. The rules are set by your organization in the prompt registry; the defaults are these.

**Accepted: change requests.** Creating, modifying, or deleting cloud infrastructure managed with Terraform, and questions that resolve directly into such a change. Missing parameters never block a request: naming conventions supply names, resource templates supply settings, and the existing workspace supplies placement (resource group, region, environment). "Create a new storage account", with nothing else, is accepted, and the response states the defaults and assumptions applied.

**Answered, not executed: informational questions.** "Which resources exist in this repository?", "How could this be improved?", "What is the impact of changing X?". Nebula answers in the chat and the round ends without changes. You can follow up with a change request in the same session.

**Declined**, with the reason shown to you:

| Reason | Example | How to fix it |
|---|---|---|
| Out of scope | "Restart the web server", "What's the difference between blob and file storage?" | Ask for a Terraform-managed change, or accept that it is a question. |
| Prohibited | Opening a security group to the world on port 22, granting `*` on `*`, disabling encryption, deleting a database without protection | Your organization's forbidden-actions list applies regardless of how the request is phrased. Ask for the compliant alternative. |
| Ambiguous target | "Rename the subnet" when the workspace has five subnets | Name the resource: "rename subnet `app-subnet-01` to `app-subnet-web`". |
| Missing referent | "Add a rule to the web firewall" when no firewall exists in the workspace | Create it first, or point at the right repository or path. |

Practical rules:

- **One intent per request.** "Add a private storage account for application logs" is better than a list of six unrelated changes. Use follow-ups for the next step.
- **Name existing resources exactly** when you modify or delete them.
- **Say what matters to you, not how to write HCL.** Size, tier, region, exposure, retention, and naming intent are useful. Nebula applies your organization's conventions for the rest.
- **Do not paste secrets.** Request text, the files the agent reads, and the plan are sent to the configured language model and stored in the tracing system. Reference secrets by name or vault path.
- **Prefer additive changes.** Standalone deletions are flagged by the default compliance rules and lock the session (see section 8).

Examples that work well: "Create a private S3 bucket named `demo-platform-logs` with versioning and default encryption for application logs." "Open port 443 from the load balancer subnet to the web security group." "Upgrade the PostgreSQL flexible server in `envs/dev` to 16."

## 5. Following the session

The progress screen shows an assistant animation, a progress bar, and one short first-person status sentence at a time, such as what is being generated or which validation error is being fixed. Progress moves through these stages:

| Stage | What Nebula is doing | Typical duration |
|---|---|---|
| Filtering | Reading and classifying your request | Seconds |
| Generating | Writing or editing Terraform files and pushing them to the session branch | Minutes |
| Validating | Running `init`, `validate`, and `plan` in the engine; feeding errors back to the generator (up to five attempts) | Minutes; longer for large roots |
| Report | Checking for drift on the touched resources and writing the report | Minutes |

A session is bounded: five generate-and-validate attempts, then a drift check of at most two passes, then the report. Browser notifications ("Pipeline completed", "Request rejected", "Session blocked", "Pipeline failed") can be enabled from the *Configuration* icon in the header.

You can close the tab. The session continues on the server; reopen it from the **Sessions** panel in the footer or from your user page (section 10).

**If it fails.** The round is marked failed with a reason: most often "Validation loop exceeded." when the engine kept rejecting the code after five attempts, or an engine or repository error. A failed session cannot be resumed ("This session failed and can't be resumed"); start a new one, usually with a more specific request. Long inactivity shows "Connection timed out — no response from server"; reload the page and open the session from the footer.

**If your login expires** you see "Your session has expired. Please sign in again." The Nebula session keeps running; sign in and reopen it.

## 6. When the request is declined or answered

You are taken to the results screen with the chat on the left. The filter's explanation, or the answer to your question, is the last assistant message. Nothing was changed and no branch was pushed for that round. Type a new request in "Ask a follow-up question..." to continue in the same session; earlier rounds' results stay visible on the right.

## 7. Reading the results

The results screen has the chat on the left and a panel with three tabs on the right.

**Plan tab.** The engine's plan text as produced by `plan`. This is the authoritative description of what would change.

**Code tab.** The files Nebula created or modified in this round, as diffs.

**Report tab.** Nebula's summary of the plan:

- **Execution Summary.** A paragraph describing the change.
- **Potential Impact.** One of *Low Impact*, *Medium Impact*, or *High Impact*, with a description. With the default criteria, high means destructive actions, restarts, downtime, or critical networking changes; medium means significant configuration updates that change behaviour without guaranteed downtime; low means isolated new resources or non-disruptive updates such as tags or locks. Click the card for the status, description, and detail bullets.
- **Estimated Cost.** A monthly figure (and the derived hourly figure) for resources with a **fixed** price. Usage-based and free resources are listed in the breakdown as "Usage-based" or "Free" and are not included in the total. Treat the figure as an approximation for comparison, not as a quote; prices come from public pricing pages at generation time.
- **Changes table.** Filter by *All*, *Created*, *Updated*, *Deleted*, *Recreated*. Each row names the resource with a short note; click it for the description and the raw plan detail.

For drift sessions the report shows a *Drift Summary*, an outcome (Succeeded, Partial, Failed), and a *Remediated Resources* list with the file, the change, and the reason for each. Two further sections appear only when the round left drift behind, and they mean different things:

- **Drift Not Reconciled.** Drift Nebula could *not* fix — the remediation ran out of iterations, or the drift could not be read at all. Each entry gives the reason and what still differs. This is what makes an outcome *Partial*; act on it.
- **Left Alone by Exception Rules.** Drift Nebula deliberately did not touch, because one of your platform's drift exception rules covers it. Each entry names the change and quotes the rule. This is the intended behaviour and does not lower the outcome, so a report can say *Succeeded* and still list entries here.

**What you do not see.** The compliance audit that runs after the report produces rule-level findings, but they are not displayed in the application. If the audit fails you see its consequence, the lock (next section), and the reviewers who receive the notification see the summary. Ask your reviewer or platform team for the details.

**Reading order that works.** Impact level first, then the Deleted and Recreated filters, then the plan for anything you do not expect, then the cost.

## 8. If the session is locked

A session is locked automatically when the compliance audit fails or, where your deployment enables it, when the impact is *High*. You are notified ("Session blocked") and, when you try to continue with a pull request, you see the **High Impact Deployment** screen: the changes have been blocked, the support team has been notified, and a specialist will review your request. Two buttons: *Back to Report* and *Contact Team*.

While locked you can still read everything, continue the conversation, and create the pull request so reviewers can read the diff. You cannot merge it or apply: the server answers that the session is blocked. A reviewer with the appropriate panel role unlocks the session from the admin portal, or you send a new request whose result passes cleanly, which clears the lock. Your own sessions list shows the lock state in the *Apply* column.

## 9. Pull request, merge, and apply

1. **Create PR.** In the results view choose *Create PR*. Nebula writes the title and description and opens the pull request from the session branch on your Git provider. Creating it can take a minute.
2. **Review.** "Here is your Pull Request." Use *View Pull Request* to open it (the button appears when the link points at a recognised host; otherwise copy the link from the session details). Your team's normal review and CI apply. If reviewers ask for changes, type them as a follow-up request; the new round pushes to the same branch and updates the pull request.
3. **Approve PR and Apply.** When the review is done, choose *Approve PR and Apply*. A confirmation asks you to confirm that you read and understood the report and the proposed changes; *Request Review* sends a support request instead, *Confirm and Apply* merges the pull request into the default branch and starts the apply. In a drift-remediation session the button only merges: the merge is the remediation, no apply follows, and you return to the report.
4. **Apply.** The engine executes exactly the plan you reviewed; it is not re-planned. The report's own status is `Success`, `Partial`, or `Failed`, shown on the apply-results screen as *Succeeded*, *Partially Applied*, or *Failed*, together with the execution summary, the resources created, updated, destroyed, or failed, and recommendations. A failed apply still closes the session normally — it is not retried and nothing is rolled back; read the error and start a new request.

After an apply the reviewed plan is consumed. To change something else, send a new request; a fresh plan is produced and reviewed before the next apply. *Import Infrastructure* in the mode drop-down currently performs this same apply step on an existing session; it does not yet import unmanaged resources ([Operating modes](modes.md)).

## 10. Coming back to a session

- **Footer.** On the start screen, the *Sessions* panel lists your most recent sessions with date, request, and project. *View all* opens the full list.
- **User page** (the user icon in the header). *Profile* (name, e-mail, *Log out*), *Session History* with *View all sessions*, and, for reviewers, *Admin Panel*.
- **Your sessions list.** Search by project, request text, or session id; filter by type and status. Open a row for the timeline of rounds, the statuses, the artifacts (report, plan, changed files, viewed inline), the session id, path, scope, repository link, and pull request links. **Reload Session** reopens it in the wizard so you can create the pull request, apply, or continue the conversation. Failed sessions cannot be reloaded.

Only you and reviewers with a panel role can see your sessions. Nobody else can act on them.

## 11. Getting support

- **Support** (chat-bubble icon in the header). Describe your question or issue in up to 500 characters and press *Send*. The message is delivered with your e-mail, the session id, the repository, branch, request, status, and a link to the session, so you do not need to copy those in. Plain text only; HTML or code formatting is rejected.
- **Contact Team** (on the locked-session screen) and **Request Review** (on the apply confirmation) send a pre-filled support request about the current session, flagged as a warning when the plan deletes or recreates resources.

Support requests go to the people who hold the reviewer roles in your Nebula deployment, through the channel your platform team connected (Slack in the reference setup), with a copy addressed to you. "Your question has been sent successfully" confirms delivery. If your deployment has not enabled notifications you see "Your question could not be sent. Notifications are disabled."; use your organization's usual support channel and quote the session id.

When reporting a problem, include: the session id (from the session details), the mode, the repository and path, what you asked, and what you expected. Reviewers can open the session's full history and the traces behind it.

## 12. Limits at a glance

| Limit | Value |
|---|---|
| Request and follow-up text | 500 characters |
| Cloud scope | 64 characters, letters, digits, and hyphens |
| Support message | 500 characters |
| Generate-and-validate attempts per request | 5 |
| Drift check inside a generate round | 2 passes |
| Drift remediation session | 3 iterations |
| One operation per session at a time | A second request while one is running is ignored until it finishes |
| Live progress stream | About 3 hours per connection; reopen the session afterwards |
| Roles | `developer`: generate, pull request, apply. `devops`: also drift remediation. |
