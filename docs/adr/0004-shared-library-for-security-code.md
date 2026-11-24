# 0004: One shared library for security-critical code

Status: Accepted (2026-11-24)

## Context

Four MCP servers (CRM, Finance, Email, Knowledge) each need the same things: who is calling
(`current_user`), the account-ownership rule, error types that don't leak details, settings,
and a database pool. Phase 5 will replace the dev-header identity with token validation; phase
6 adds more checks. If each server had its own copy, every security fix would have to land in
four places, and the one that is missed becomes the way in.

## Options

| Option | For | Against |
|---|---|---|
| Copy the code into each server | Each service fully independent; simplest builds | Copies drift; a fix missed in one server is a vulnerability |
| A separate auth microservice | One place, language-neutral | A network hop on every call; a single point of failure; still needs a client in each server |
| **A shared Python library (`libs/northstar-common`)** | One implementation, tested once; no network hop; each server still checks every request itself | Docker builds need the repo root as context; a library change affects every server at once (which is the point) |

## Decision

`libs/northstar-common` holds identity (`current_user`), errors (`Unauthenticated`, `Forbidden`,
`NotFound`), the account-scope rule (`see_all` defaults to false), `UntrustedText`, the settings
base class, the connection pool lifespan, read-only and read-write transactions, and the server
runner. Each server depends on it by local path, keeps only its own rules and tools, and has a
thin `auth.py` that passes its own `*_DEV_AUTH` setting.

## Consequences

Good:
- Phase 5's token validation changes one function body; all four servers get it together.
- The identity tests (14) run once, in the library.
- New servers are small: Finance, Email and Knowledge each added only their own rules.

Bad:
- Images are built from the repo root, with a root `.dockerignore` to keep secrets and tests out.
- A bug in the library affects every server; the library's tests and each server's tests both
  guard against that.
