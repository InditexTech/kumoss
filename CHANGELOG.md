# Changelog

## [1.1.0](https://github.com/InditexTech/kumoss/compare/v1.0.9...v1.1.0) (2026-11-26)

> [!WARNING]
> This release contains **breaking changes**. Read the [upgrade notes](https://inditextech.github.io/kumoss/stable/main/guides/upgrade-notes/) before rolling out.

### Highlights

- **Deterministic compliance with OPA.** Generate rounds now check the final plan against Rego policies evaluated with Open Policy Agent: one general policy plus one per declared provider.
- **Intent check.** The LLM half of the compliance check is narrowed to an intent check: does the plan do what the session's requests ask?
- **Langfuse replaces Arize Phoenix** for traces and prompts.
- **Root module manifest.** Providers, scopes, and input variables are read from a `kumoss.yaml` manifest in the root module instead of being asked for in the wizard.
- **Sidecar contracts 2.0.0.** The IaC, authorization, and mapping sidecar contracts move to 2.0.0 together.

### Platform

- The core runs **Alembic migrations** at startup.
- A **mapping sidecar** now ships with Kumoss.
- The core runs on **Python 3.15**.

### Before you upgrade

- **Custom sidecars** must be upgraded together with the core.
- **Phoenix prompts** customized prompts have to be migrated to Langfuse.
- **`forbidden_actions` prompts** are no longer enforced, required ones must be migrated to OPA REGO rules.
- **Kumoss-managed Terraform state** must be copied to its new keys.


### ⚠ BREAKING CHANGES

* **contracts:** the IaC, authorization and mapping sidecar contracts move to 2.0.0, so custom implementations must be upgraded along with the core. IaC requests are plain CLI invocations: commands take `env`, and `plan`/`import` also take `vars`, and `scope_id`, `terraform_provider` and `variables` are removed. The bundled IaC service no longer checks the AWS account with STS. Mapping requests take `identifier` only, and the core's `POST /api/v1/mapping/resolve` passthrough is removed ([#525](https://github.com/InditexTech/kumoss/issues/525), [#527](https://github.com/InditexTech/kumoss/issues/527)) ([e5f95bd](https://github.com/InditexTech/kumoss/commit/e5f95bd36c6a48b5ddc8150a9961a9eb4cd5300a), [fb0ba2e](https://github.com/InditexTech/kumoss/commit/fb0ba2ed9eb9d5b6e7715bc4287ed3d23b35a900))
* **langfuse:** Langfuse replaces Phoenix. `telemetry.collector_url` becomes `telemetry.langfuse_url`, and a `config.yaml` that still sets `collector_url` is refused at boot. Prompt names become folders (`aws-guidelines-networking` → `aws/guidelines/networking`). The Helm values `phoenix.*` become `langfuse.*`. Move existing prompts with `core/scripts/migrate_phoenix_prompts.py`. Traces are not migrated ([#552](https://github.com/InditexTech/kumoss/issues/552)) ([439b7f3](https://github.com/InditexTech/kumoss/commit/439b7f35855e2a53341df22638c3efdeb48c61de))
* **compliance:** the `<provider>/guidelines/forbidden_actions` prompts are no longer read, and the request filter no longer declines requests as prohibited. Only the shipped and custom compliance policies enforce prohibitions now, and bans that a policy enforces were removed from the guideline and resource prompts. Write any other rules you rely on as Rego ([#553](https://github.com/InditexTech/kumoss/issues/553), [#569](https://github.com/InditexTech/kumoss/issues/569)) ([ab04312](https://github.com/InditexTech/kumoss/commit/ab043120c7943330a8d655ca919ca7c1f596019e), [c46d2f3](https://github.com/InditexTech/kumoss/commit/c46d2f385b0107c670cbaa3ee075ca997142a805))
* **compliance:** the core image ships `opa`, and with the compliance checker on, the core refuses to start if the policies cannot be evaluated. Reports carry `policy_revisions` instead of `policy_revision`, and each finding carries a `source` (`opa` or `intent`). The LLM rules prompt moves from `general/compliance/report` to `general/intent/rules`, so port any customized version ([#553](https://github.com/InditexTech/kumoss/issues/553), [#569](https://github.com/InditexTech/kumoss/issues/569), [#575](https://github.com/InditexTech/kumoss/issues/575)) ([877562e](https://github.com/InditexTech/kumoss/commit/877562ea7ffbb34ab4bce39a8af471c33f916046))
* **manifest:** providers come from the root module's `required_providers` and are named by their Terraform provider type (`azure` → `azurerm`, `gcp` → `google`, `vmware` → `vsphere`) in the database, the prompts and the authorization requests. `generate`, `drift` and `import` no longer take `terraform_providers` or `scope_id`, and session read models expose `providers`. Kumoss-managed state keys no longer include the cloud scope, so **existing state must be copied to the new key** before running sessions on a project ([#523](https://github.com/InditexTech/kumoss/issues/523)) ([51416c2](https://github.com/InditexTech/kumoss/commit/51416c216a9f3b9d48fdc9a9e4a6febe987be2a3))
* **mapping:** a mapping sidecar is bundled and enabled by default. With it enabled, the core refuses to boot without `KUMOSS_MAPPING_TOKEN`, and the Helm chart generates that token. Set `services.mapping.enabled: false` to opt out ([#527](https://github.com/InditexTech/kumoss/issues/527)) ([fb0ba2e](https://github.com/InditexTech/kumoss/commit/fb0ba2ed9eb9d5b6e7715bc4287ed3d23b35a900))
* **authz:** the authorization contract is rewritten to the OpenID AuthZEN 1.0 Access Evaluation standard, so custom PDPs must be upgraded along with the core. The `/v1/check` endpoint and the user and role CRUD endpoints are replaced by a single `POST /v1/evaluation`, and `subject.id` is now the Kumoss user's database id instead of the OIDC `sub`. `authorize()` is enforced on every IaC write route (generate, drift, apply, import) and on PR and session mutations. With authz enabled but no endpoint, it now fails closed with `503` instead of granting access. The frontend auth preflight is removed, and `cloud_scope` is renamed `scope` ([#459](https://github.com/InditexTech/kumoss/issues/459)) ([7a510fc](https://github.com/InditexTech/kumoss/commit/7a510fcc89d009b994ac0e1998ec64c0e9a1c3bb))
* **api:** session detail returns the user-facing conversation as `chat_history`, requested with `include_chat_history=true`. The internal LLM `history` (`include_history`) is now only returned by the admin route `GET /api/v1/admin/sessions` ([#344](https://github.com/InditexTech/kumoss/issues/344)) ([997e965](https://github.com/InditexTech/kumoss/commit/997e965bfeac59b0e82d2e558fdc1a4e0a0f896b))
* **database:** Alembic migrations replace `create_all` and adopt existing databases on first start, so back the database up first. A database that has sessions but no `users` table is refused ([#526](https://github.com/InditexTech/kumoss/issues/526)) ([1a33897](https://github.com/InditexTech/kumoss/commit/1a338973770a617aac01a603dae75b10ad891fb6))
* **deps:** core, iac and notifications move to Python 3.15 ([#550](https://github.com/InditexTech/kumoss/issues/550)) ([880f115](https://github.com/InditexTech/kumoss/commit/880f11540b6815f2b6c6e6d684c83c07c1f65c25))


### Features

* **compliance:** a Rego policy (`general/policies/compliance`) runs with OPA on the final plan of every generate round and is merged into a single compliance report. `critical_deletion` moves from the prompt into this policy, and a policy that cannot be evaluated locks the session as `policy_unavailable` ([#553](https://github.com/InditexTech/kumoss/issues/553)) ([ab04312](https://github.com/InditexTech/kumoss/commit/ab043120c7943330a8d655ca919ca7c1f596019e))
* **compliance:** each declared provider can ship its own policy (`<provider>/policies/compliance`), and seeds are included for `aws`, `azurerm`, `google`, `kubernetes`, `oci` and `vsphere`. The general policy adds `customer_managed_key_removed` and `command_execution` (deny) and `unprotected_credential_output` (warn) ([#569](https://github.com/InditexTech/kumoss/issues/569)) ([c46d2f3](https://github.com/InditexTech/kumoss/commit/c46d2f385b0107c670cbaa3ee075ca997142a805))
* **compliance:** the LLM half of the check becomes an intent check. It judges only `scope_exceeded` and `scope_incomplete` and no longer returns its own verdict, so only the merged report passes or fails. The general policy adds the `provider_version_pin` warning ([#575](https://github.com/InditexTech/kumoss/issues/575)) ([877562e](https://github.com/InditexTech/kumoss/commit/877562ea7ffbb34ab4bce39a8af471c33f916046))
* **web:** every compliance finding is badged *policy* or *intent*, both in the Compliance Check artifact and on the Deployment Blocked screen ([#553](https://github.com/InditexTech/kumoss/issues/553), [#575](https://github.com/InditexTech/kumoss/issues/575)) ([877562e](https://github.com/InditexTech/kumoss/commit/877562ea7ffbb34ab4bce39a8af471c33f916046))
* **langfuse:** traces and prompts move to a self-hosted Langfuse v4 in Compose and Helm. The seeder labels prompt versions, and the admin panel links to Langfuse ([#552](https://github.com/InditexTech/kumoss/issues/552)) ([439b7f3](https://github.com/InditexTech/kumoss/commit/439b7f35855e2a53341df22638c3efdeb48c61de))
* **manifest:** root module inputs are discovered from a committed `kumoss.yaml` manifest, and the wizard asks for them only when the module needs something ([#523](https://github.com/InditexTech/kumoss/issues/523)) ([51416c2](https://github.com/InditexTech/kumoss/commit/51416c216a9f3b9d48fdc9a9e4a6febe987be2a3))
* **manifest:** a repository can be named by a project identifier. The identifier is checked against `repo_uri` through the mapping sidecar, stored on the session and in `kumoss.yaml`, and sent to the IaC service in the `Kumoss-Project` header (IaC contract 2.1.0, additive) ([#572](https://github.com/InditexTech/kumoss/issues/572)) ([b84283a](https://github.com/InditexTech/kumoss/commit/b84283a7bca105471044271a64e16c6de268c215))
* **mapping:** the wizard resolves a bare repository name through the new bundled `services/mapping` sidecar ([#527](https://github.com/InditexTech/kumoss/issues/527)) ([fb0ba2e](https://github.com/InditexTech/kumoss/commit/fb0ba2ed9eb9d5b6e7715bc4287ed3d23b35a900))
* **authz:** OIDC claims are mapped through a configurable `claims` table with per-IdP overrides and forwarded to the PDP as subject properties. A conformance suite and a stub PDP are added for the AuthZEN contract ([#459](https://github.com/InditexTech/kumoss/issues/459)) ([7a510fc](https://github.com/InditexTech/kumoss/commit/7a510fcc89d009b994ac0e1998ec64c0e9a1c3bb))
* **chat:** the session page shows a user-facing chat history, with a reply written for the user at the end of each round ([#344](https://github.com/InditexTech/kumoss/issues/344)) ([997e965](https://github.com/InditexTech/kumoss/commit/997e965bfeac59b0e82d2e558fdc1a4e0a0f896b))
* **tools:** new `terraform_docs` tool, backed by the Terraform Registry ([#418](https://github.com/InditexTech/kumoss/issues/418)) ([ba1589d](https://github.com/InditexTech/kumoss/commit/ba1589d9756acc85d5ad0c4c706022cac6b60844))
* **tools:** `web_search` fetches pages with httpx, and Playwright is removed from the core image ([#426](https://github.com/InditexTech/kumoss/issues/426)) ([d2ce5c8](https://github.com/InditexTech/kumoss/commit/d2ce5c8ad4190354610cfe0ebd6c9bc7549ab55c))


### Bug Fixes

* **web:** fix the session list filters, the assistant animation freezing, and when the PR unlock button is shown. An unfinished session now renders only its chat history ([#344](https://github.com/InditexTech/kumoss/issues/344)) ([997e965](https://github.com/InditexTech/kumoss/commit/997e965bfeac59b0e82d2e558fdc1a4e0a0f896b))
* **core:** refuse calls on busy sessions, and default the root module ([#528](https://github.com/InditexTech/kumoss/issues/528)) ([5be92c1](https://github.com/InditexTech/kumoss/commit/5be92c1628fa4be4fb0466593394da1f4660e562))
* **core:** decode stringified tool arguments before running a tool, and check compliance against every user query in the session, not just the last one ([#526](https://github.com/InditexTech/kumoss/issues/526)) ([1a33897](https://github.com/InditexTech/kumoss/commit/1a338973770a617aac01a603dae75b10ad891fb6))
* **deps:** bump litellm to 1.109.1, plus the actions, uv and node images, and the core, iac, client/web and docs dependencies ([#550](https://github.com/InditexTech/kumoss/issues/550)) ([880f115](https://github.com/InditexTech/kumoss/commit/880f11540b6815f2b6c6e6d684c83c07c1f65c25))


### Documentation

* **upgrade-notes:** new upgrade notes page that lists every change in this release that needs action ([#523](https://github.com/InditexTech/kumoss/issues/523), [#552](https://github.com/InditexTech/kumoss/issues/552), [#553](https://github.com/InditexTech/kumoss/issues/553), [#572](https://github.com/InditexTech/kumoss/issues/572), [#575](https://github.com/InditexTech/kumoss/issues/575))
* **compliance:** document the OPA compliance policy, the provider policies and the intent check. Restructure the compliance and prompt docs and group the navigation ([#553](https://github.com/InditexTech/kumoss/issues/553), [#569](https://github.com/InditexTech/kumoss/issues/569), [#573](https://github.com/InditexTech/kumoss/issues/573)) ([02b7dab](https://github.com/InditexTech/kumoss/commit/02b7dab7590fa2079fe6d7f50beb32cf9ea599bb))
* **guides:** explain why a session locks and how an editor unlocks it, in a new *Resolve a locked session* guide, and show where compliance findings appear in a session ([#568](https://github.com/InditexTech/kumoss/issues/568), [#570](https://github.com/InditexTech/kumoss/issues/570)) ([840430f](https://github.com/InditexTech/kumoss/commit/840430fd136cf5eb9599cee6e8b67245e5e25f0e), [061175a](https://github.com/InditexTech/kumoss/commit/061175aba6545710ec730eda7750182137bb7065))
* **guides:** restructure *Follow a session* around an example report, and move the drift report explanation into *Remediate drift* ([#571](https://github.com/InditexTech/kumoss/issues/571)) ([661f613](https://github.com/InditexTech/kumoss/commit/661f6135e704e6bc688bb063b873c14cfc6b15e7))
* **langfuse:** describe Langfuse in place of Phoenix in a new *Monitor with Langfuse* guide ([#552](https://github.com/InditexTech/kumoss/issues/552)) ([439b7f3](https://github.com/InditexTech/kumoss/commit/439b7f35855e2a53341df22638c3efdeb48c61de))
* **roadmap:** mark OPA and the Helm chart done ([#568](https://github.com/InditexTech/kumoss/issues/568)) ([840430f](https://github.com/InditexTech/kumoss/commit/840430fd136cf5eb9599cee6e8b67245e5e25f0e))
* use US English spelling throughout the site ([#573](https://github.com/InditexTech/kumoss/issues/573)) ([02b7dab](https://github.com/InditexTech/kumoss/commit/02b7dab7590fa2079fe6d7f50beb32cf9ea599bb))

## [1.0.9](https://github.com/InditexTech/kumoss/compare/v1.0.8...v1.0.9) (2026-11-19)


### Bug Fixes

* **nginx:** bump the web image's nginx base to 1.31.9 to fix [CVE-2026-123007](https://www.cve.org/CVERecord?id=CVE-2026-123007) ("nginx2root"), an HTTP/2 flow-control integer underflow (CVSS 4.0 9.2) that can corrupt the heap and allow remote code execution in the worker process; it affects nginx 1.9.5 through 1.31.8 and is fixed in 1.31.9 (mainline) and 1.30.7 (stable). The base image is now pinned as `tag@digest` so the version is visible in reviews and scans ([#524](https://github.com/InditexTech/kumoss/issues/524)) ([5e095c9](https://github.com/InditexTech/kumoss/commit/5e095c90afe75ebfbf936345d07d8714f748eb9f))
* **deps:** bump dnspython to 2.9.2 in core, iac and notifications ([GHSA-vvf4-9x63-8xvv](https://osv.dev/GHSA-vvf4-9x63-8xvv)) ([#521](https://github.com/InditexTech/kumoss/issues/521)) ([b56e946](https://github.com/InditexTech/kumoss/commit/b56e9461db929094ff2e868cf073a430b9159a57))


### Documentation

* **quickstart:** point Kubernetes users to the published OCI Helm chart and the kind trial ([#497](https://github.com/InditexTech/kumoss/issues/497)) ([de614f6](https://github.com/InditexTech/kumoss/commit/de614f6c9371e2c196d040f491b5168b9b93db92))
* **readme:** add an OpenTofu compatibility badge ([#492](https://github.com/InditexTech/kumoss/issues/492)) ([0d9e2ae](https://github.com/InditexTech/kumoss/commit/0d9e2aecde23eb72a45f2e745f6ce227a22acba7))
* **readme:** clarify the Kumoss project description ([#498](https://github.com/InditexTech/kumoss/issues/498)) ([917648f](https://github.com/InditexTech/kumoss/commit/917648fa05be17512fc9c81e84fdc1ac3c81ccee))

## [1.0.8](https://github.com/InditexTech/kumoss/compare/v1.0.7...v1.0.8) (2026-11-05)


### Bug Fixes

* **config:** raise the default `llm.max_output_tokens` from 32000 to 64000 ([#467](https://github.com/InditexTech/kumoss/issues/467)) ([46c20f3](https://github.com/InditexTech/kumoss/commit/46c20f34f5983847d4745d41af6f81f30f965e29))
* **nginx:** revalidate index.html and return 404 for missing hashed assets instead of HTML ([#464](https://github.com/InditexTech/kumoss/issues/464)) ([e4a2fce](https://github.com/InditexTech/kumoss/commit/e4a2fceb76dd2addfefcb4fa8c6b21f1c922b0f6))
* **pr_service:** stop the PR service crashing on creation; `web_search` moves to the workspace tool registry ([#466](https://github.com/InditexTech/kumoss/issues/466)) ([611268a](https://github.com/InditexTech/kumoss/commit/611268a4dc5467ddd33b1bdfe5be6d5610c997b9))

## [1.0.7](https://github.com/InditexTech/kumoss/compare/v1.0.6...v1.0.7) (2026-11-04)


### Features

* **ci:** publish the SearXNG image to GHCR ([540120b](https://github.com/InditexTech/kumoss/commit/540120b25d969abc58b1a7db0ad8f3b240a05aa5))


### Bug Fixes

* **ci:** build searxng from its own context and resolve its image tag ([f5fd25c](https://github.com/InditexTech/kumoss/commit/f5fd25c4a74ffac9120489e2f1a28edd0adcdaf5))
* **searxng:** honour a supplied settings path and escape the secret ([e9ff814](https://github.com/InditexTech/kumoss/commit/e9ff814f73578d81ac1d6b5d217ac115026b4ec5))

## [1.0.6](https://github.com/InditexTech/kumoss/compare/v1.0.5...v1.0.6) (2026-11-03)


### Features

* **helm:** add caBundle to trust extra CA roots in every outbound pod ([d5280d3](https://github.com/InditexTech/kumoss/commit/d5280d3759467ce49048cef74304f726ca63c31d))
* **helm:** add kind-up.sh to bring the chart up on kind in one command ([15141ea](https://github.com/InditexTech/kumoss/commit/15141eafcde3cb9a8903ee2eaa491bf7b06475cf))
* **helm:** caBundle for all outbound pods, kind-up.sh, and OCI chart publishing ([605f4c3](https://github.com/InditexTech/kumoss/commit/605f4c33386160cc8c84484da37456446466dc1e))


### Bug Fixes

* **core:** trust every certificate in multi-certificate CA files ([636331d](https://github.com/InditexTech/kumoss/commit/636331d54956fc1ccac92f4fde47ac6676907574))
* **helm:** keep glued certificates in caBundle and set AWS_CA_BUNDLE ([6170f03](https://github.com/InditexTech/kumoss/commit/6170f03d476c1bb10a8fff16e829e438f4519369))
* **helm:** validate the chart before kind-up.sh touches the cluster ([81c49a8](https://github.com/InditexTech/kumoss/commit/81c49a8bf0c20a4b2400d06ae1faa4d746ee8c5b))


### Documentation

* **helm:** document caBundle, kind-up.sh and the OCI chart ([bcb0fcb](https://github.com/InditexTech/kumoss/commit/bcb0fcb34c5c22f2182aa40db865593871cbe34a))

## [1.0.5](https://github.com/InditexTech/kumoss/compare/v1.0.4...v1.0.5) (2026-11-02)


### Features

* **helm:** deploy Kumoss on Kubernetes with a Helm chart ([#456](https://github.com/InditexTech/kumoss/issues/456)) ([df35e14](https://github.com/InditexTech/kumoss/commit/df35e14cacffb625b419b4d26270a6f3eeb04942))


### Bug Fixes

* **core:** answer `GET /healthz` so orchestrators can probe the core ([#456](https://github.com/InditexTech/kumoss/issues/456)) ([3429bfe](https://github.com/InditexTech/kumoss/commit/3429bfe67768604f31d94aafb6a71ffe7171e261))


### Documentation

* add the Deploy with Helm guide for kind, AKS, EKS and GKE ([#456](https://github.com/InditexTech/kumoss/issues/456)) ([df35e14](https://github.com/InditexTech/kumoss/commit/df35e14cacffb625b419b4d26270a6f3eeb04942))

## [1.0.4](https://github.com/InditexTech/kumoss/compare/v1.0.3...v1.0.4) (2026-11-02)


### Bug Fixes

* **deps:** bump graphql-core to 3.3.1 ([GHSA-mpqx-q82w-9x46](https://osv.dev/GHSA-mpqx-q82w-9x46)) ([b5e416a](https://github.com/InditexTech/kumoss/commit/b5e416afe558d8b0daf438fc3b9102e279c735dc))
* **deps:** bump pyasn1 to 0.6.5 in core and iac ([GHSA-2qm8-x737-gmw5](https://osv.dev/GHSA-2qm8-x737-gmw5), [GHSA-9m75-vc3g-4x39](https://osv.dev/GHSA-9m75-vc3g-4x39), [GHSA-fm9c-5rcf-2q5p](https://osv.dev/GHSA-fm9c-5rcf-2q5p), [GHSA-mm57-4v3p-rchx](https://osv.dev/GHSA-mm57-4v3p-rchx)) ([b5e416a](https://github.com/InditexTech/kumoss/commit/b5e416afe558d8b0daf438fc3b9102e279c735dc))
* **docs:** upgrade docouture to 1.3.2 so search links keep the site path ([34ad0a9](https://github.com/InditexTech/kumoss/commit/34ad0a90c9dc3dde1232937ac5384f042eaaf9d3))


### Documentation

* add README audience section and roadmap table ([a153a17](https://github.com/InditexTech/kumoss/commit/a153a173970ed530d98c01591d1c4dfb9d1a65d4))
* use the white README banner in every theme ([f63c4ef](https://github.com/InditexTech/kumoss/commit/f63c4efba6a164231699bb03349d64e60e32a0cb))

## [1.0.3](https://github.com/InditexTech/kumoss/compare/v1.0.2...v1.0.3) (2026-10-29)


### Bug Fixes

* **deps:** bump dnspython to 2.9.0 ([GHSA-45c3-73f7-pv4m](https://osv.dev/GHSA-45c3-73f7-pv4m)) ([db959e4](https://github.com/InditexTech/kumoss/commit/db959e4a869170ca3d340973a04c98b823f2cb93))


### Documentation

* add QuickStart section to README ([75ab278](https://github.com/InditexTech/kumoss/commit/75ab278fa17fbd499bfe0d83629504ff3c4d5e2c))
* add real-run demo video to README and docs site ([56f1e6d](https://github.com/InditexTech/kumoss/commit/56f1e6d7f90bb01e86b4bff0b87b61d3f95e3349))
* add roadmap section to README ([2482f02](https://github.com/InditexTech/kumoss/commit/2482f0213ac72f1927ba8bb5c65934111a890108))
* simplify README roadmap section ([087c43a](https://github.com/InditexTech/kumoss/commit/087c43a6e24f238337db09b328c69cb9137a4154))
* update real-run demo video ([ab32583](https://github.com/InditexTech/kumoss/commit/ab325830ce23e8220cae6358713687825e95ee68))
* update real-run demo video with sharper cloud console footage ([07fb52e](https://github.com/InditexTech/kumoss/commit/07fb52ea5ae0d2cc05d291632c856a5363d71efc))

## [1.0.2](https://github.com/InditexTech/kumoss/compare/v1.0.1...v1.0.2) (2026-10-26)


### Bug Fixes

* **iac:** increase iac plan target max limit to 4096 ([9ce8752](https://github.com/InditexTech/kumoss/commit/9ce8752e0777e753a9d0db1c932c8b6f1732eca7))
* **import:** build import IDs in the provider's documented format ([769eafd](https://github.com/InditexTech/kumoss/commit/769eafd5b07bc96f8d521f75e59272e80f4a9b1c))
* **import:** remove unused `status` tool field - steer the model to use web_search - listed_id always present ([54ad0a5](https://github.com/InditexTech/kumoss/commit/54ad0a52b21b1c0b23ad718d2110b2df4df7caf8))
* **tests:** update import tests ([5f34aa3](https://github.com/InditexTech/kumoss/commit/5f34aa324e607821b0fb0d5bea1e6a5b0527cb52))

## [1.0.1](https://github.com/InditexTech/kumoss/compare/v1.0.0...v1.0.1) (2026-10-23)


### Bug Fixes

* **ci:** pass the host-certs build context when publishing images ([afbc217](https://github.com/InditexTech/kumoss/commit/afbc21711c0906b74c1f3f6305ae7dd81d6cba64))
* **deps:** Bump dompurify to 3.4.17 and graphql-core to 3.2.13 ([5f5ec61](https://github.com/InditexTech/kumoss/commit/5f5ec6117951402ddafd5f8c7816404168001ef7))
* Publish the core image and bump OSV-flagged dependencies ([978ad13](https://github.com/InditexTech/kumoss/commit/978ad1329b1d254fdb75170262e729d862b02739))

## Changelog
