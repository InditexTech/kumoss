# IaC service: `CloudCli` orchestrator and per-provider classes

**Date:** 2026-09-08
**Scope:** `services/iac` only. No contract change.
**Status:** Approved design, awaiting implementation plan.

## Problem

`services/iac/src/main.py` carries logic that belongs in `cloud_cli`:

- `_scope_env` decides which cloud providers have complete credentials and
  builds the engine environment. `cloud_cli._configured_providers` makes the
  same decision independently for startup login. The two copies already
  disagree (main only reports Azure as missing when it is partially set).
- The `state_resource_ids` handler pulls state, parses it, and synthesizes a
  JSON result inline.
- Neither test suite exercises the `CredentialError` path, and a partially
  configured provider (for example `ARM_CLIENT_ID` without `ARM_CLIENT_SECRET`)
  is silently skipped at boot instead of failing the deployment.

Inside `cloud_cli.py`, each provider concern lives in a separate structure:
`CLI_BINARIES`, `_configured_providers`, the `if provider == ...` chain in
`list_resource_ids`, and module-level login state (`_last_login`,
`_login_lock`). Adding a provider means touching four places.

## Goal

Organize the existing functionality without changing the HTTP contract:

1. One class per provider owning readiness, login, scope environment, and
   resource listing.
2. One `CloudCli` orchestrator owning the provider instances and login state,
   created once in `main.py`.
3. Startup validation that fails the boot when any provider is partially
   configured, aggregating every offending provider into one error.
4. `main.py` reduced to routing and job submission.

## Non-goals

- Changing `contracts/openapi/iac.v1.yaml`. `terraform_provider` stays
  required on scope-resource-ids and the endpoint queries one provider only.
- Endpoint deduplication, health-check readiness, or the 500 handler's detail
  text. These were noted in review and are separate changes.
- Any change to how engine or CLI subprocesses authenticate. Credentials keep
  flowing through the inherited process environment.

## Package layout

`src/cloud_cli.py` becomes the package `src/cloud_cli/`:

```
src/cloud_cli/
  __init__.py   # re-exports CloudCli, CloudProvider, PROVIDERS
  _cli.py       # CloudCli orchestrator
  _base.py      # CloudProvider ABC, shared _run(), _failure(), _ids_result()
  _azure.py     # AzureProvider
  _gcp.py       # GcpProvider
  _aws.py       # AwsProvider
```

Provider files receive their existing login and listing code moved verbatim
from today's `_az_login_sp`, `_gcloud_auth`, `aws_assume_role`, `_list_azure`,
`_list_gcp`, and `_list_aws`. The listing logic (Resource Graph paging, KQL
escaping, gcloud result-shape tolerance, AWS region enumeration and
`_AwsRegionError`) does not change.

## `CloudProvider` contract (`_base.py`)

```python
class CloudProvider(ABC):
    name: ClassVar[str]          # contract value: "azure" | "gcp" | "aws"
    display_name: ClassVar[str]  # "Azure" | "GCP" | "AWS", for logs and errors
    cli_binary: ClassVar[str]    # "az" | "gcloud" | "aws"

    def __init__(self, config: Config) -> None: ...

    @abstractmethod
    def credential_env(self) -> dict[str, str]:
        """Required env var name -> current value ('' when unset)."""

    def missing_env(self) -> list[str]:
        """Names in credential_env() whose value is empty."""

    def is_configured(self) -> bool:
        """At least one credential var is set."""

    def is_ready(self) -> bool:
        """Every credential var is set (missing_env() is empty)."""

    @abstractmethod
    async def login(self) -> None:
        """Authenticate the CLI. Raises RuntimeError on failure."""

    @abstractmethod
    async def scope_env(self, scope_id: str) -> dict[str, str]:
        """Extra engine env for a job scoped to scope_id."""

    @abstractmethod
    async def list_resource_ids(self, scope_id: str) -> CommandResult:
        """JSON array of resource ids on stdout, or a failure result."""

    def cli_available(self) -> bool:
        """shutil.which(cli_binary) is not None."""
```

All answers come from `config`, never from `os.environ`. That is why `Config`
gains the two AWS fields below.

| | Azure | GCP | AWS |
|---|---|---|---|
| `credential_env` | `ARM_CLIENT_ID`, `ARM_CLIENT_SECRET`, `ARM_TENANT_ID` | `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CREDENTIALS` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` |
| `missing_env` | base default | overridden: `["GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_CREDENTIALS"]` when neither is set, else `[]` | base default |
| `login` | `az login --service-principal ... --allow-no-subscriptions` | `gcloud auth activate-service-account` with the temporary key file when only inline JSON is set | no-op (ambient keys) |
| `scope_env` | `{"ARM_SUBSCRIPTION_ID": scope_id}` | `{"GOOGLE_PROJECT": scope_id}` | AssumeRole credentials when `config.aws_terraform_role_name` is set; `RuntimeError` and `OSError` from AssumeRole are logged at debug and yield `{}` (non-AWS scope ids are expected to fail); `{}` when no role is configured |
| `list_resource_ids` | Resource Graph with skip-token paging | asset search plus IAM roles | caller-identity check or AssumeRole, then Tagging API per enabled region |

`AwsProvider` keeps AssumeRole as a private method `_assume_role(scope_id)`
used by both `scope_env` and `list_resource_ids`.

GCP readiness is "either var set". The base `is_ready` is defined as
`not self.missing_env()`, so the GCP override of `missing_env` is sufficient.

## `CloudCli` orchestrator (`_cli.py`)

```python
PROVIDERS: tuple[type[CloudProvider], ...] = (AzureProvider, GcpProvider, AwsProvider)

class CloudCli:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._providers = [cls(config) for cls in PROVIDERS]
        self._last_login = 0.0
        self._login_lock = asyncio.Lock()
```

| Method | Replaces | Behavior |
|---|---|---|
| `validate_credentials()` | new | For each provider: if `is_configured()` and not `is_ready()`, collect `display_name -> missing_env()`. If anything was collected, raise `MissingCredentialError(missing)`. Zero configured providers passes. |
| `ready_providers()` | `_configured_providers` | Providers with `is_ready()`. Logs one info line per skipped provider naming its missing vars, as today. |
| `login(*, retries=0)` | `cloud_login` | Same double-check locking, per-provider independent attempts, exponential backoff `retry_delay * 2**(n-1)` retrying only failed providers, single `RuntimeError` naming all failures, `_last_login` untouched on failure. |
| `ensure_login()` | `ensure_cloud_login` | `login(retries=config.cloud_login_retries)` when `needs_relogin()` is true. |
| `needs_relogin()` | `needs_relogin` | Uses instance `_last_login` and `config.cloud_login_refresh_min`. |
| `scope_env(scope_id)` | `main._scope_env` | If no provider is ready, raise `CredentialError({display_name.lower(): missing_env()} for every provider)`. Else start from `dict(os.environ)` and merge `await p.scope_env(scope_id)` for every ready provider, in `PROVIDERS` order. |
| `state_resource_ids(binary, workspace, env)` | inline in `main` | `engine.state_pull`; on failure return `CommandResult(ok=False, stdout="", stderr, exit_code)`; on success return `_ids_result(engine.extract_managed_resource_ids(stdout))`. |
| `scope_resource_ids(provider, scope_id)` | `list_resource_ids` | Look up the provider by `name`; unknown name returns the existing `_failure("Unsupported terraform_provider: ...", exit_code=2)`. Delegate to `list_resource_ids`. |
| `cli_available(provider)` | `cli_available` | Look up by `name`; `False` for unknown names; else `provider.cli_available()`. |

`main.py` never imports a provider class or `engine.state_pull`.

## Config changes

Two env-backed fields added to `Config` and `Config.from_env`:

| Field | Env var |
|---|---|
| `aws_access_key_id` | `AWS_ACCESS_KEY_ID` |
| `aws_secret_access_key` | `AWS_SECRET_ACCESS_KEY` |

They are used only for readiness. `env.sample` documents them and its AWS
comment is updated: both vars are now required for AWS to count as configured,
and setting only one is a startup error.

## Errors

New exception in `models.py` beside `CredentialError`:

```python
class MissingCredentialError(Exception):
    """A provider has some but not all of its credential env vars set."""
    def __init__(self, missing: dict[str, list[str]]) -> None:
        self.missing = missing
        parts = [f"{prov}: {', '.join(fields)}" for prov, fields in missing.items()]
        super().__init__(
            "Incomplete cloud credentials; set every variable for a provider "
            "or none of them. Incomplete: " + "; ".join(parts)
        )
```

| Exception | Raised from | Meaning | Effect |
|---|---|---|---|
| `MissingCredentialError` | `CloudCli.validate_credentials`, startup only | Deployment is misconfigured | Boot aborts, container exits |
| `RuntimeError` | `CloudCli.login` | Credentials complete but login rejected | Startup: boot aborts. Per job: job fails 500 after retries |
| `CredentialError` | `CloudCli.scope_env`, per job | No provider is ready for this job | Job fails 422 via `jobs._run`, unchanged |

## Startup sequence (`main.lifespan`)

1. `configure_logging`, `tf.set_timeout`, log engine availability. Unchanged.
2. `cloud.validate_credentials()`.
3. `await cloud.login(retries=0)`.
4. Any exception from 2 or 3 is logged with `logger.exception` and re-raised.

## `main.py` after the change

- `cloud = CloudCli(config)` created at module level next to `jobs`.
- Imports of `os`, `json`, `CredentialError`, and `engine.state_pull` removed.
- `_scope_env` deleted. Every pipeline calls `await cloud.ensure_login()`
  then `env = await cloud.scope_env(body.scope_id)`.
- `state_resource_ids` pipeline:
  `_result(await cloud.state_resource_ids(config.iac_binary, workspace, env))`.
- `scope_resource_ids`: submit-time 503 uses `cloud.cli_available(...)` and
  the message reads the binary name from the provider class; pipeline calls
  `cloud.scope_resource_ids(body.terraform_provider, body.scope_id)`.
- Module docstring gains one sentence: the two `/v1/import/*-resource-ids`
  endpoints return a synthesized JSON array on stdout rather than raw engine
  output.

Caller-visible behavior is unchanged: same status codes, same job result
shapes, same error mapping.

## Testing

All new code is written test-first. `tests/test_cloud_cli.py` is reorganized
into one section per provider class and one for `CloudCli`.

New coverage:

- Per provider: `missing_env`, `is_configured`, `is_ready` for empty, partial,
  and complete configs. GCP with either var alone is ready.
- `validate_credentials`: passes with zero providers; passes with one complete
  provider; raises for one partial provider; raises once naming both when two
  providers are partial.
- `scope_env`: raises `CredentialError` with the expected missing map when
  nothing is ready; injects `ARM_SUBSCRIPTION_ID` and `GOOGLE_PROJECT`; merges
  AssumeRole output when AWS is ready and a role is configured; swallows
  AssumeRole failure for non-AWS scope ids.
- `state_resource_ids`: JSON id list on success; exit code and stderr passed
  through on state-pull failure.
- Startup: booting with a partial Azure config aborts with
  `MissingCredentialError`.

Moved coverage keeps its assertions and changes only patch targets:

| Today | After |
|---|---|
| `patch("src.cloud_cli._az_login_sp")` | `patch.object(AzureProvider, "login")` |
| `patch("src.cloud_cli._gcloud_auth")` | `patch.object(GcpProvider, "login")` |
| `patch("src.cloud_cli.aws_assume_role")` | `patch.object(AwsProvider, "_assume_role")` |
| `patch("src.cloud_cli.cli_available")` | `patch.object(service_main.cloud, "cli_available")` |
| `patch("src.cloud_cli.list_resource_ids")` | `patch.object(service_main.cloud, "scope_resource_ids")` |
| `patch("src.cloud_cli.ensure_cloud_login")` | `patch.object(service_main.cloud, "ensure_login")` |
| `cloud_cli._last_login = 0.0` | `service_main.cloud._last_login = 0.0` |

`test_api._client_with` builds a fresh `CloudCli` for the per-test `Config`
and assigns it to `service_main.cloud`, alongside the existing swap of
`service_main.config` and `service_main.jobs`.

`test_config.py` asserts the two AWS fields are read from the environment.

Verification: `uv run pytest` and `ruff check` in `services/iac` on the host.
`test_integration_engine.py` is untouched.

## Migration

One branch, commits in this order, each leaving the suite green:

1. `Config` fields and `MissingCredentialError`, with tests.
2. `cloud_cli/` package: `_base.py` and the three providers, with per-provider
   tests. The old module is deleted in the same commit.
3. `CloudCli` in `_cli.py`, with orchestrator tests.
4. `main.py` rewired; `test_api.py` and `test_hardening.py` patch targets
   updated; `env.sample` updated.

Nothing outside `services/iac` imports `cloud_cli`, so there is no
compatibility period.
