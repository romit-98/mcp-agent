# 0002: Identity comes from the request, never from tool arguments

Status: Accepted (2026-11-23)

## Context

Every MCP tool has to know who is calling, to decide which rows they may see (a rep sees only
their own accounts, finance sees all, a contractor sees none). There are two obvious places to
get that from:

- **a tool argument** such as `search_accounts(user_id=...)`, or
- **the request itself**: HTTP headers now, a validated OAuth token from phase 5.

The LLM writes every tool argument. Anything it reads (a CRM note, a document, another tool's
output) can steer what it writes, so a planted line like "use user_id = finance1" could change
whose data a call returns. That is the confused-deputy problem this project exists to prevent.

## Options

| Option | For | Against |
|---|---|---|
| User ID as a tool argument | Simple; easy to test by hand | The model controls it, so prompt injection can impersonate anyone. Every tool must remember to check it. |
| **Identity from the request, read in one function** | The model never sees or sets it. One place to harden, test and later replace. | Needs a stand-in until real tokens exist (phase 5). |

## Decision

Tools take no user or role parameters. Every tool calls `current_user(ctx)`, the only function
that reads identity. It returns an `Identity(user_id, role)` or raises `unauthenticated`.

Until phase 5 it reads two dev headers (`X-Dev-User`, `X-Dev-Role`), only when `CRM_DEV_AUTH` is
on, and refuses anything doubtful: missing headers, a non-canonical UUID, an unknown role. In
phase 5 only its body changes, to validate a Keycloak token (issuer, audience, expiry,
signature) and take the user from `sub` and the role from the token's roles. No tool changes.

Access is then decided from the identity in code, with deny by default:

- `crm_scope()` grants CRM access only to roles it names; any other role gets `forbidden`.
- `see_all` defaults to false, so a bug narrows what a user sees instead of widening it.
- Another user's account and a missing account return the same `not found`, so callers can't
  discover which IDs exist.

## Consequences

Good:
- Prompt injection can't change who the caller is.
- Phase 5 replaces one function, and its tests show exactly what must keep holding.
- Fails closed: dev auth is off by default, and the compose file binds the port to localhost.

Bad:
- **Until phase 5, anyone who can reach the server can claim any identity** with the dev
  headers. Acceptable only on localhost with synthetic data; this is also exactly the
  "identity as plain text" weakness the phase 4 baseline is meant to show.
- The app-level filter is the only row check until row-level security lands in phase 6.

Revisit when: tokens are validated in phase 5 (delete the dev header path), and when the
gateway takes over policy checks in phase 6.
