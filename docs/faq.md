<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# Frequently asked questions

Short answers for people using the Nebula web application. The longer explanations are in the [user guide](user-guide.md); mode-by-mode behaviour is in [Operating modes](modes.md).

## Access and roles

**Why are the drift modes and Import Infrastructure greyed out?** They require the `devops` operation role. New users start as `developer`. Ask your administrator to change your role in the admin portal; it takes effect on your next page load.

**Can other people see my sessions?** Only reviewers who hold a panel role (viewer, editor, or admin) can read them, including the conversation. Nobody but you can continue, merge, or apply your sessions.

**Why does the login page say my session has expired?** Your identity token expired and the application signed you out. Sign in again. Any Nebula session that was running continues on the server; reopen it from the footer or your user page.

## Requests

**Do I have to specify every parameter?** No. Missing parameters never block a creation request. Nebula applies your organization's naming conventions, resource defaults, and the placement it finds in the workspace, and it states the assumptions it made in the response.

**My request was declined. Why?** The filter explains the reason in the chat. The four causes are: out of scope (not a Terraform-managed change), prohibited by your organization's forbidden-actions list, an ambiguous target (name the resource), or a missing referent (the thing you refer to does not exist in that repository and path).

**Can I ask questions instead of requesting changes?** Yes. Inventory, improvement, and impact questions are answered in the chat; the round ends without changes and you can continue with a change request in the same session.

**Can I request several changes at once?** You can, but one intent per request produces better results and clearer reports. Use follow-ups for the next step; they run on the same branch.

**Why was my repository URL rejected?** URLs that embed a user name or token are refused; enter the plain HTTPS URL. Azure DevOps users: the portal's clone URL starts with `https://<org>@dev.azure.com/...`; remove the `<org>@` part. Only `github.com`, `gitlab.com` (no subgroups), and `dev.azure.com` are supported for pull requests. The repository must also be reachable by Nebula's service account.

**Why does Nebula say it found no IaC paths?** It only sees files committed on the repository's default branch, and it offers a directory only when it contains `.tf` files and no part of its path is `modules`, `examples`, `example`, or `.terraform`. Commit the Terraform files to the default branch, or move them out of an excluded directory. The rules are in [Operating modes](modes.md#how-nebula-finds-terraform-roots).

**Why is my directory not offered as an IaC path?** Either it sits under an excluded directory name, or it is nested under another directory that already qualifies as a root (for example `platform/network/` under a `platform/` that has a `main.tf`); in that case pick the parent, Nebula works from there.

**Why does the scope field not accept my value?** It accepts letters, digits, and hyphens only, up to 64 characters, and lower-cases the value. Underscores, dots, and spaces are not accepted.

## Sessions

**How long does a session take?** From a couple of minutes for a small change to considerably longer for large roots: generation and up to five validation attempts run first, then a drift check and the report. The progress screen shows what is happening at each moment.

**Can I close the browser?** Yes. The session runs on the server. Reopen it from the *Sessions* panel in the footer or from *View all sessions* on your user page.

**Why can't I continue a failed session?** A failed round ends the session for good. Start a new session; if the failure was "Validation loop exceeded.", make the request more specific or split it.

**Why does nothing happen when I send a second request while one is running?** Only one operation runs per session at a time. Wait for the current round to finish; the input is disabled during a run.

**What is the branch called?** `Nebula/<date>_<time>` in UTC, created on the first request of the session. Every round pushes to it.

## Results

**What do Low, Medium, and High impact mean?** With the default criteria: high is destructive actions, restarts, downtime, or critical networking changes; medium is a significant configuration update that changes behaviour without guaranteed downtime; low is isolated new resources or non-disruptive updates such as tags.

**Is the estimated cost accurate?** It is an approximation of fixed monthly prices for the resources in the plan, taken from public pricing pages when the report was written. Usage-based and free resources are listed but not included in the total. Use it to compare options, not as a quote.

**Where are the compliance findings?** They are not displayed in the application. The audit's outcome is visible as the lock; the reviewers who receive the notification see the summary. Ask them for the rule-level detail.

**Can I download the plan or the report?** Not as files. The plan, report, and changed files are shown inline in the results view and in the session details; the code itself is on the session branch in your repository.

## Locks and approvals

**Why is my session locked?** The compliance audit found an error-level or critical violation (with the default rules: changes outside the scope of your request, parts of the request left undone, or a standalone deletion), or the impact was rated High in a deployment that locks on high impact.

**What can I do while locked?** Read everything, continue the conversation, and create the pull request so reviewers can see the diff. Merging and applying are refused.

**How is a lock released?** A reviewer with the editor or admin panel role unlocks the session from the admin portal, or a new request in the same session produces a result that passes cleanly.

**Why is a deletion I explicitly asked for flagged?** The default compliance rule treats any standalone deletion as a critical violation regardless of the request; only a recreate of the same resource is allowed. A reviewer can unlock the session after looking at it, and your organization can adapt the rule.

## Pull requests and apply

**Do I have to open a pull request?** The API allows a direct apply, but the web application does not offer a standalone Apply button. In practice you reach apply either through *Approve PR and Apply*, which merges the pull request and then applies, or through the *Import Infrastructure* mode in the header drop-down, which calls the same apply on the current session and is only selectable with the `devops` role. So as a `developer` in the web application, the pull request is the route to apply — which is also the recommended one, because it brings your team's review and CI into the decision.

**Reviewers asked for changes. What now?** Type the changes as a follow-up request in the same session. The new round pushes to the same branch, so the pull request updates.

**What exactly does Approve PR and Apply do?** After you confirm, it merges the pull request into the default branch and executes the plan you reviewed, without re-planning. The apply-results screen shows what happened.

**The apply failed. Will Nebula retry?** No. The session still closes as completed, with an apply report whose status is *Failed* and a notification to your reviewers; nothing is rolled back and nothing is re-run. Read the error in the apply results, fix the cause (often cloud permissions or a resource that changed since the plan), and send a new request, which produces a fresh plan to review.

**Does Import Infrastructure import my existing resources?** Not yet. Today it runs the apply of an existing session's reviewed plan. Importing unmanaged resources is a planned capability.

**Where does Terraform state live?** Not in the repository, and not in the working copy Nebula creates. Out of the box, Nebula keeps state for you, in a bucket dedicated to state with one state file per project (repository + cloud scope + path). Your platform team can instead configure Nebula to leave it in the remote backend your repository's own Terraform files declare, exactly as it would if you ran the engine yourself. Either way your pull request contains only your infrastructure code — no state file and no backend file — and there is nothing for you to set per session; the details are in [Terraform/OpenTofu state backends](terraform-state-backends.md).

**My plan wants to create resources that already exist. Why?** The session is planning against empty state. The usual causes are that your platform team turned off Nebula-managed state and your repository declares no remote backend of its own, that the project's identity changed — the root-module path moved, the repository was renamed, or a different cloud scope was selected — or that your platform team changed the state backend, which Nebula never migrates. Report it with the session id; an operator can check the state location.

## Data and privacy

**What data leaves Nebula when I make a request?** Your request text, the conversation, the repository files the agent reads, the plan, and validation errors are sent to the language model your platform team configured and stored in the tracing system for review. Do not paste secrets into requests or commit them to the repository.

**Which cloud credentials does Nebula use?** The identity your platform team configured for the execution engine, never yours. Your deployment can also plug in an external authorization service that is asked, at the start of each session, whether you may work on that cloud, repository and IaC path; in the shipped configuration that service is switched off and no such check runs.

## Getting help

**How do I contact support?** Use the chat-bubble *Support* icon in the header, or *Contact Team* on a locked session. The message carries your e-mail, the session id, and the session context automatically and reaches the reviewers of your deployment.

**Support says notifications are disabled.** Your deployment has not connected a notification channel. Use your organization's usual support route and quote the session id from the session details.

**What should I include when reporting a problem?** The session id, the mode, the repository and path, what you asked, and what you expected instead. Reviewers can then open the session's history, artifacts, and traces.
