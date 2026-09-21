<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# Mapper resolve: repo URL plus best-effort provider and scope

Date: 2026-09-21
Status: approved, not yet implemented

## Problem

`POST /v1/resolve` answers "which repo does this identifier mean?" and
returns `{repo_url, project, branch, path}`. Only `repo_url` is used.
`project` is echoed by the core passthrough into `ResolveResult.project`
and read by nobody; `branch` and `path` are unwrapped into `ResolvedRef`
and read by nobody.

Meanwhile the wizard asks the user for three more things after the
repository: the IaC path, the Terraform provider, and the cloud scope. An
organization whose catalogue already knows the provider and scope for a
project has no way to supply them, so its users retype facts the mapper
could have answered.

## Solution

Reshape the resolve response to carry what the wizard actually needs, and
have the wizard skip any step the mapper already answered.

```
ResolveRequest              ResolveResponse
  identifier: str             repo_url:           str
  terraform_provider:         identifier:         str
    TerraformProvider|null    terraform_provider: TerraformProvider|null
                              scope_id:           str|null
```

Removed: `cloud` and `environment` from the request; `project`, `branch`
and `path` from the response.

### Semantics

`repo_url` is what `git clone` targets. When the identifier already is a
repository URL, implementations pass it through unchanged.

`identifier` is the request's `identifier`, echoed verbatim. This is
normative, not a convention: callers correlate on it.

`terraform_provider` echoes the request's value when one was sent;
otherwise it is the implementation's best-effort answer, or `null`.

`scope_id` is the implementation's best-effort cloud scope — Azure
subscription id, GCP project id, AWS account id, OCI compartment OCID —
or `null`.

**`null` means "I do not know, ask the user."** It does not mean "there is
none". This distinction is load-bearing: the wizard silently skips any
step the mapper answered, so a confidently wrong answer sends the user
into a plan against the wrong scope with no prompt to catch it.

How an implementation turns a true business identifier into a repo URL,
a provider and a scope is entirely its own concern. The contract carries
the result and says nothing about the lookup.

### Versioning

Edited in place: `contracts/openapi/mapping.v1.yaml` keeps its filename,
its `POST /v1/resolve` path, and `info.version: "1.0.0"`. The contract has
no external consumers to migrate yet, and the repo's pre-release posture
is to change schemas rather than hedge with parallel versions.

## Design

### Contract — `contracts/openapi/mapping.v1.yaml`

Add a `TerraformProvider` schema mirroring `iac.v1.yaml` verbatim:

```yaml
TerraformProvider:
  type: string
  enum: [azure, gcp, aws, oci, kubernetes]
```

`ResolveRequest`: `required: [identifier]`, `identifier` unchanged
(1..1024), new nullable `terraform_provider`. `ResolveResponse`:
`required: [repo_url, identifier]`, `repo_url` unchanged (1..2048),
`identifier` 1..1024, nullable `terraform_provider`, nullable `scope_id`
(1..1024, mirroring `iac.v1.yaml`'s `scope_id`). Both keep
`additionalProperties: false`.

Nullable enum references use the OpenAPI 3.1 form
`anyOf: [$ref TerraformProvider, {type: "null"}]`. No contract in this
repo uses `anyOf` today, so the generator's rendering of it is unverified.
If `openapi-python-client` 0.29.0 produces an awkward type, fall back to
inlining the enum at both sites as `type: [string, "null"]` with the enum
values plus `null`, and note the fallback in the PR.

`info.description` and the per-field descriptions are rewritten. The
current text promises "clone URL, default branch, and optional
subdirectory" and describes the reference implementation as returning "a
`project` echoing the identifier" — all of it now wrong. The new text
states the best-effort contract and the meaning of `null` explicitly.

### Reference service — `services/mapping/`

Stays an identity passthrough:

```python
return ResolveResponse(
    repo_url=body.identifier,
    identifier=body.identifier,
    terraform_provider=body.terraform_provider,
    scope_id=None,
)
```

`src/models.py` gains a `TerraformProvider(str, Enum)` and the reshaped
request/response models.

No heuristics. Sniffing `azure` out of a `dev.azure.com` URL would
conflate "hosted on Azure DevOps" with "deploys to Azure", and under
silent skipping a wrong guess is unrecoverable without a full wizard
reset. Provider is whatever the caller sent; scope is always `null`.

The `body.identifier[:128]` truncation disappears with `project`.
`identifier` shares the request's 1024-character cap, so the response no
longer silently mangles long inputs.

### Generated client — `core/src/clients/mapping/`

Regenerated, then post-processed per the repo's two undocumented steps
(prepend the SPDX header to every `.py`; fold
`from typing_extensions import Self` into the file's `typing` import).

The committed `mapping` client was generated by an older
`openapi-python-client` than the pinned one, so a wholesale regenerate
rewrites files that have nothing to do with this change (`-> T` becoming
`-> Self`, and the matching import edit). That churn would bury the real
diff.

Therefore: generate twice — once from
`git show HEAD:contracts/openapi/mapping.v1.yaml`, once from the working
tree — and diff the two *generated* trees against each other. Install only
files in that delta. Expected: `models/terraform_provider.py` (new),
`models/resolve_request.py`, `models/resolve_response.py`,
`models/__init__.py`.

### Core — `core/src/`

`infrastructure/external/mapping_service.py`:

```python
@dataclass(frozen=True)
class ResolvedRef:
    repo_url: str
    identifier: str
    terraform_provider: TerraformProvider | None = None
    scope_id: str | None = None

async def resolve(self, identifier: str, *,
                  terraform_provider: TerraformProvider | None = None) -> ResolvedRef
```

`ResolvedRef` carries core's `shared.constants.TerraformProvider`, never
the generated client's. Conversion happens at the boundary —
`MappingTerraformProvider(provider.value)` outbound,
`TerraformProvider(response.terraform_provider.value)` inbound — using the
alias-import pattern `infrastructure/terraform/terraform.py` already uses
for the iac client.

The disabled path returns
`ResolvedRef(repo_url=identifier, identifier=identifier,
terraform_provider=terraform_provider, scope_id=None)` — byte-identical to
what the reference service would answer, so toggling `mapping.enabled`
changes nothing for a user who pastes a repo URL.

**Unhandled-error fix.** The generated `ResolveResponse.from_dict` calls
`TerraformProvider(d.pop(...))`, which raises `ValueError` on a value
outside the enum. That happens inside `resolve_op.asyncio`, and the
current `try` catches only `httpx.TimeoutException` and
`httpx.RequestError` — so an implementation returning `"azurerm"` escapes
as an unhandled 500. Add `ValueError` to the caught set, mapped to 502,
matching the existing "mapping service returned an unexpected response"
handling.

`api/v1/mapping.py`: the body gains `terraform_provider` and drops
`cloud`/`environment`. The handler's hand-rolled `JSONResponse` dict is
replaced by a `MappingResolveResponse` in `api/dtos.py` plus
`response_model=` on the route — the pattern `api/v1/notifications.py`
already uses. The endpoint currently publishes no schema, only a prose
example, while `client/web/src/types/api_mapper.ts` is hand-written
against it; a real schema lets the two be checked instead of drifting.

### Frontend — `client/web/src/`

New `hooks/wizardFlow.ts` holds the entire skip decision as a pure
function:

```ts
export function nextStep(data: WizardData): WizardStep | "complete" {
  if (!data.query) return "query";
  if (!data.repositoryUrl) return "repository_url";
  if (!data.iacPath) return "iac_path";
  if (!data.provider) return "provider";
  if (!data.cloudScope) return "cloud_scope";
  return "complete";
}
```

"First input still missing, else complete." Skipping is not special-cased:
a step is skipped precisely because the mapper already filled its slot.

`useWizardNavigation` gains `applyResolution(patch): WizardData`, which
merges into `data`, calls `setData`, and returns the merged object. The
return is required, not a convenience: when the mapper supplies provider
and scope, both are written and consumed in the same tick, so
`navigation.data` still holds the pre-merge value from the current render.
Today's code reads `navigation.data` after `setData` safely only because
each step is a separate user interaction in a separate render.

`useHomeWizard` gains `advance(data)`, which either calls
`navigation.setStep(next)` or fires `auth.run(...)` on `"complete"`. Four
call sites funnel through it: the `repository_url` branch of `handleInput`,
`handlePath`, `handleProvider`, and the `cloud_scope` branch.
`updateSession({provider, scope_id})` moves alongside so session state is
written whether a value came from the user or the mapper.

This restructuring is the point of the change. `auth.run` fires today from
exactly one place — the `cloud_scope` branch — which is safe only because
`cloud_scope` is always last. Once the mapper can fill those slots, the
wizard becomes complete at three different moments, and bolting skipping
onto the existing `if/else` leaves one of them silently never authorizing.

`ResolveResult` becomes `{repoUrl, identifier, provider, scopeId, paths}`.

The wizard never sends `terraform_provider` on the request:
`resolveAndScan(identifier)` keeps its single argument, and resolution
runs at the `repository_url` step, before the user has picked a provider.
The field exists on the request type
(`terraform_provider?: TerraformProvider | null` in `types/api_mapper.ts`)
for contract completeness and for callers other than the wizard.

Resulting behaviour for a single-IaC-path repo:

| mapper returns | steps shown after `repository_url` |
|---|---|
| neither | `provider` → `cloud_scope` |
| provider only | `cloud_scope` |
| scope only | `provider` |
| both | none — straight to authorization |

Multi-path repos insert `iac_path` first. Zero-path repos still error
out unchanged.

**Mapper-supplied `scope_id` is not validated.** Typed scopes are checked
against `/^[a-zA-Z0-9-]+$/` and lowercased. That pattern is a human-typo
guard and is already too strict — an OCI compartment OCID
(`ocid1.compartment.oc1..aaaa…`) contains dots and fails it. Applying it to
mapper output would reject a correct OCI answer and drop the user onto a
step where they cannot type a valid one either. The mapper is a trusted
internal service and the contract bounds `scope_id` to 1..1024 characters.

The same pattern rejects OCI scopes typed by hand on `main` today. That is
a pre-existing bug, out of scope here, and deliberately not fixed as a
side effect.

`retry()` needs no new logic: it already clears all four data fields when
recovering from a mapper error, and on an authorization error it returns
to `cloud_scope` with `cloudScope` cleared — which doubles as the escape
hatch for a mapper that supplied a wrong scope.

## Testing

Tests are written before the code they cover.

- `services/mapping/tests/test_api.py` — reshaped response;
  `terraform_provider` echoed when sent, `null` when not; `scope_id`
  always `null`; 422 for a provider outside the enum.
- `core/tests/test_mapping_in_request_path.py` — disabled-config identity
  including provider survival; enabled-path enum conversion both
  directions; the new `ValueError → 502` guard.
- `client/web/src/hooks/wizardFlow.test.ts` (new) — the skip matrix as a
  table: every combination of provider × scope × path-count against
  `nextStep`. This test is what approach A exists to make possible.
- `useMapperResolution.test.ts` — reshaped `ResolveResult`.
- `useHomeWizard.test.ts` — the integration claim the pure test cannot
  make: provider and scope resolved ⇒ `auth.run` fires and neither step
  renders.
- `contracts/conformance/mapping/` — no edit needed (spec-driven), but
  running it against the reference service parse-checks the contract and
  exercises the new enum end to end.

## Documentation

- `services/mapping/README.md` — documents the old `{repo_url, project}`
  return in prose and in a `curl` example.
- `docs/architecture.md` — "Resolves a business identifier to repo
  URL/branch/path".
- Grep `docs/` for the `project`/`branch`/`path` vocabulary around
  mapping.

## Verification

All verification runs in containers, per the project's established
recipes: core unittest in the compose core container, `services/mapping`
pytest via the uv image, frontend `tsc`/`vitest`/`build` in `node:20-slim`,
ruff via the ruff image, and the Schemathesis suite against the running
reference service. Core's suite has a known baseline of pre-existing
failures; results are reported as a diff against a HEAD baseline rather
than as a clean run.

## Order of work

1. Contract
2. Reference service
3. Regenerate the client (spec-delta only) — this is where the
   `anyOf: [$ref, null]` question is settled
4. Core
5. Frontend

The regenerated client gates everything downstream of it.
