<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# OIDC setup

Nebula authenticates against any OIDC-compliant identity provider. The
minimal configuration is two fields in `config.yaml`:

```yaml
oidc:
  issuer_url: "https://your-idp.example.com"
  client_id: "your-client-id"
```

Leaving `issuer_url` blank disables authentication entirely (the dev
default): every request acts as a local developer with top roles.

`config.yaml` is baked into the `nebula-core` image at build time.
To load a different file, point the `NEBULA_CONFIG` env var at its path.

## Provider support

Nebula works with any spec-faithful OIDC provider that supports the
authorization code flow with PKCE for public SPA clients, publishes a
discovery document with a JWKS endpoint, and issues **JWT access
tokens** (RS*/ES*/PS* signed) carrying `iss`, `aud`, and `exp`.

| Provider | Support | Config |
|---|---|---|
| Microsoft Entra ID | ✅ | `issuer_url` + `client_id` (scope auto-derived) |
| Keycloak | ✅ | `issuer_url` + `client_id` (audience mapper in the realm) |
| Auth0 | ✅ | `issuer_url` + `client_id` + `audience` (API identifier) |
| Okta | ✅ | `issuer_url` + `client_id` + `audience` (the custom authorization server's audience, e.g. `api://default`) |
| AWS Cognito | ❌ not out of the box | see limitation below |
| Google Identity | ❌ | access tokens are opaque strings, not JWTs — nothing to validate against JWKS |

Auth0 and Okta list `audience` because they issue access tokens for a
registered API resource whose identifier is an arbitrary string chosen
when you set it up at the IdP (an Auth0 API identifier, an Okta
authorization server audience) — it cannot be derived from
`client_id`, so copy it into `audience`. Entra ID and Keycloak issue
tokens whose `aud` is the client id itself, which the core already
accepts when `audience` is blank.

> **Known limitation — AWS Cognito:** Cognito access tokens are JWTs
> but carry **no `aud` claim** (a `client_id` claim instead) and **no
> `email` claim**, so the core rejects them and user provisioning /
> `admin.default_root_email` matching would have no email to work
> with. Cognito's ID tokens would pass validation unchanged, so
> support would need an opt-in "send the ID token as bearer" toggle
> (plus real-world testing of Cognito's nonstandard Hosted UI logout).
> This is not implemented today.

## Registering the app at your IdP (all providers)

- Register a **public SPA client** using the **authorization code flow
  with PKCE**. No client secret is used anywhere.
- Redirect URI: `<origin>/auth/callback` (e.g.
  `http://localhost/auth/callback` for the docker-compose stack).
- Post-logout redirect URI: `<origin>`.

## Microsoft Entra ID

1. **App registrations → New registration.** Add a **Single-page
   application** platform with redirect URI `<origin>/auth/callback`.
2. **Expose an API → Add a scope.** Accept the default Application ID
   URI (`api://<client-id>`) and name the scope anything (e.g.
   `access_as_user`). This step is required: without it Entra has no
   scope to grant for the app itself.
3. Configure:

   ```yaml
   oidc:
     issuer_url: "https://login.microsoftonline.com/<tenant-id>/v2.0"
     client_id: "<application-client-id>"
   ```

   That's all: for `login.microsoftonline.com` issuers the core
   automatically appends `api://{client_id}/.default` to the login
   scopes, which requests the exposed scope(s) without needing their
   names. Leave `audience` blank — both the bare client id and
   `api://<client-id>` are accepted as the token audience, covering
   both Entra access-token versions.

> **Gotchas:** the auto-scope only triggers when `scope` is left unset;
> set it explicitly to request specific scopes
> (`scope: "openid profile email api://{client_id}/access_as_user"` —
> `{client_id}` is expanded automatically). Sovereign clouds
> (`login.microsoftonline.us`, …) are not auto-detected: set `scope`
> explicitly there too. Without any `api://…` scope in the request,
> Entra issues the access token for Microsoft Graph and the core
> rejects it with a 401 audience mismatch. Entra tokens often omit the
> `email` claim — the core falls back to `preferred_username`, so
> bootstrap-admin matching via `admin.default_root_email` still works.

## Keycloak

1. Create a **public client** (Standard flow on, Direct access grants
   off) with valid redirect URI `<origin>/auth/callback`.
2. Keycloak does not put the client_id in `aud` by default: add an
   **Audience mapper** (client scopes → dedicated scope → add mapper →
   Audience) targeting your client.
3. Configure:

   ```yaml
   oidc:
     issuer_url: "https://<keycloak-host>/realms/<realm>"
     client_id: "<client-id>"
   ```

   The default scope (`openid profile email`) suffices; leave
   `audience` blank.

## Auth0

1. Create a **Single Page Application** with callback URL
   `<origin>/auth/callback` and logout URL `<origin>`.
2. Create an **API** (its identifier becomes the token audience) —
   Auth0 only issues JWT access tokens when an audience is requested.
3. Configure:

   ```yaml
   oidc:
     issuer_url: "https://<tenant>.auth0.com"
     client_id: "<client-id>"
     audience: "<api-identifier>"
   ```

   The frontend forwards `audience` on the authorize request — Auth0
   requires it there to issue a JWT access token. Auth0 emits `iss`
   with a trailing slash; the core accepts the issuer with or without
   it, so the `issuer_url` above works as written.

## Okta

1. **Applications → Create App Integration → OIDC, Single-Page
   Application**, with sign-in redirect URI `<origin>/auth/callback`
   and sign-out redirect URI `<origin>`. Assign the app to your
   users/groups.
2. Access tokens come from an authorization server (**Security → API →
   Authorization Servers**): copy its **Issuer URI** and **Audience**.
   The default custom server uses issuer
   `https://<okta-domain>/oauth2/default` and audience `api://default`.
3. Configure:

   ```yaml
   oidc:
     issuer_url: "https://<okta-domain>/oauth2/default"
     client_id: "<client-id>"
     audience: "api://default"
   ```

   `audience` must match the authorization server's audience setting
   verbatim (it is not derived from the client). The default scope
   suffices.

## Field reference

| Field | Default | Meaning |
|---|---|---|
| `issuer_url` | `""` | OIDC issuer. Blank disables auth (dev mode). |
| `client_id` | `""` | The registered SPA client. Required when `issuer_url` is set. |
| `audience` | `""` | Optional override of the expected token audience; blank accepts `client_id` and `api://<client-id>`. |
| `scope` | `"openid profile email"` | Scopes the SPA requests at login. `{client_id}` is expanded at load; Entra ID issuers auto-append `api://{client_id}/.default` when left at the default. |
| `clock_skew_seconds` | `60` | Leeway on `exp`/`iat`/`nbf` validation. |

Related: `admin.default_root_email` in `config.yaml` elevates the user
whose token email matches it to the top role of both role groups at
login (one-way; blank to skip).

## Troubleshooting

- **401 "Token validation failed … audience"** — the access token's
  `aud` doesn't match `audience`/`client_id`. Entra: the app doesn't
  expose an API scope, or a sovereign-cloud issuer skipped the
  auto-scope (set `scope` explicitly). Keycloak: missing audience
  mapper. Auth0: `audience` not set in `config.yaml`. Okta: `audience`
  doesn't match the authorization server's audience setting.
- **Login redirect rejected by the IdP** — the redirect URI
  `<origin>/auth/callback` isn't registered exactly (scheme, host,
  port).
- **Config changes have no effect** — rebuild the core image
  (`docker compose build core`); the file is baked in.
- **Check what the SPA received** — `curl http://localhost/api/v1/auth/config`
  returns the exact values served to the frontend (with `{client_id}`
  already expanded).
