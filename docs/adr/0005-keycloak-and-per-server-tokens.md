# 0005: Keycloak locally, with one exchanged token per server

Status: Accepted (2026-11-28)

## Context

Every MCP server must know who the user is (rule 10) and accept only tokens issued for it
(rule 4: no token passthrough). Until now identity came from dev headers, which anyone who can
reach a server can forge. v1 must run on a laptop; phase 8 moves to Azure, where Microsoft
Entra ID is the natural identity provider. The Deakin tenant can't be used for app
registrations or test users.

## Options

| Option | For | Against |
|---|---|---|
| **Keycloak in Docker** | Runs locally and free; standard OIDC; standard token exchange (RFC 8693, GA since 26.2); realm is a reviewable JSON file | Another container; dev mode isn't production config |
| Microsoft Entra ID now | Same as production on Azure; On-Behalf-Of flow | Needs a tenant I control; cloud dependency for every local run; slower to iterate |
| Self-signed JWTs from our own code | No extra service | Rolling our own identity provider is exactly what not to do |

## Decision

Keycloak 26.8 in Docker, realm `northstar` imported from `keycloak/import/northstar-realm.json`:

- Five users with the **same fixed UUIDs as `iam.users`**, so the token's `sub` is the database
  user ID. Realm roles `sales_rep`, `finance_analyst`, `contractor`.
- One client per server (`mcp-crm`, `mcp-finance`, `mcp-email`, `mcp-knowledge`), each with an
  `access` client role. Realm roles are composites of the servers that role may use, so a
  contractor's roles include only `mcp-knowledge` (and the gateway).
- `northstar-agent` (confidential) signs users in and exchanges token A for one token per
  server, with `audience` set to that server. `northstar-gateway` is ready for phase 6.
- Every server validates: RS256 signature against the realm's JWKS (no `none`, no HS256),
  exact issuer, expiry and not-before with 30 s of skew, `typ` is `Bearer` (not an ID token),
  `sub` is a canonical UUID, exactly one known role, and **audience is exactly this server**.
- Secrets (admin password, client secrets, the dev users' password) are generated into `.env`
  and substituted into the realm at import; none are in the repo.
- `--hostname http://localhost:8180` keeps `iss` identical whether Keycloak is called from the
  laptop or from another container at `http://keycloak:8080`.

### Why "audience is exactly this server"

Checked against the real Keycloak: the sign-in token (token A) lists **every** server the user
may use in `aud`. A server that only checked "my name is in `aud`" would accept token A, so the
agent could pass one token everywhere. Requiring the audience to be exactly the server forces a
fresh exchange per server, and the exchange is where Keycloak enforces which servers a role
may reach.

## Consequences

Good:
- Forged headers no longer work; identity is a signed token the model never sees.
- Three layers already say no to a contractor reading invoices: Keycloak won't issue a Finance
  token, the agent therefore has no Finance tools, and the Finance server refuses the role.
- Tests prove it: 34 unit tests (expired, wrong audience, wrong issuer, forged, `alg: none`,
  algorithm confusion, ID token, bad subject, missing or ambiguous role), and 8 live tests
  against Keycloak and the CRM server.

Bad:
- Dev mode uses the password grant for the CLI agent; a real UI (later) uses the
  authorization code flow with PKCE.
- JWKS keys are fetched synchronously on a cache miss (every 5 minutes at most).
- Dev headers still exist behind `*_DEV_AUTH` (off by default) for tests; a bad token never
  falls back to them.

Revisit when: moving to Entra ID in phase 8 (On-Behalf-Of replaces token exchange; the
validation rules stay the same), or when the gateway takes over the exchange in phase 6.
