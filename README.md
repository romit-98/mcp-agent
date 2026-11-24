# secure-mcp-agent

An enterprise AI agent that calls company tools through MCP and acts strictly as the signed-in
user. Most enterprise agents have more access than the person using them (the "confused deputy"
problem). Here every permission is enforced in code, not in the prompt: OAuth token exchange
carries the user's identity to each MCP server, OpenFGA decides which tools they may call,
Postgres row-level security decides which rows they may see, and a gateway checks argument
provenance, requires bound single-use approvals for writes, redacts sensitive fields and writes a
hash-chained audit log. The demo company is Northstar Logistics, a fictional Australian freight
company with fully synthetic data. An open eval suite measures leakage, injection success,
over-refusal and gateway latency for an insecure baseline and the secured stack.

## Architecture

```
Browser ──► Web UI (chat + approval screen)
               │ token A (audience: agent)
               ▼
            Agent API (LangGraph: planner, step/cost limits, approval interrupts)
               │ token B (audience: gateway), obtained by token exchange
               ▼
            MCP Gateway (validate → policy → argument check → approval → redact → audit → trace)
               │ token C (audience: one server, short-lived), obtained by token exchange
               ├──► CRM server ──┐
               ├──► Finance server ├──► PostgreSQL (row-level security + pgvector)
               ├──► Knowledge server┘
               └──► Email server (mock)

Supporting: Keycloak (identity), OpenFGA (policy), LLM provider, OpenTelemetry collector
```

### Security layers

| Layer | Enforced by | Blocks |
|---|---|---|
| Tool | OpenFGA | A contractor calling Finance at all |
| Row | Postgres row-level security | A rep reading another rep's accounts, even if app code has a bug |
| Argument | Gateway provenance check | Untrusted text choosing an email recipient, account or amount |
| Action | Approval bound to a hash of (user, tool, arguments, expiry), single use | A credit note issued or changed without sign-off |
| Record | Hash-chained audit log | Silent tampering |

## Permissions

| Role | CRM | Finance | Knowledge | Email |
|---|---|---|---|---|
| Sales rep | Own accounts only | Invoices for own accounts, read only | Staff docs | Internal staff + contacts on own accounts |
| Finance analyst | All accounts, read only | All invoices; credit notes always need approval | Staff + finance docs | Internal only |
| Contractor | None | None | Contractor-shared docs only | None |

Nobody can read HR-confidential docs in v1. They exist to test that retrieval never leaks them.

## Build phases

- [x] 1. Repo, database, synthetic data
- [x] 2. CRM MCP server
- [ ] 3. Finance, Knowledge, Email servers
- [ ] 4. Insecure baseline agent
- [ ] 5. Identity (Keycloak)
- [ ] 6. Gateway and security layers
- [ ] 7. Eval harness and CI
- [ ] 8. Azure deployment

Definitions of done: [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md), section 8.

## Decision records

- [0001: pgvector in Postgres instead of a separate vector database](docs/adr/0001-pgvector-in-postgres.md)
- [0002: Identity comes from the request, never from tool arguments](docs/adr/0002-identity-from-the-request.md)

## Quick start

Requires Docker Desktop.

```sh
cp .env.example .env          # Windows cmd: copy .env.example .env
                              # then set a real POSTGRES_PASSWORD in .env
docker compose up -d
docker exec -it northstar-postgres psql -U northstar -d northstar -c "\dx"
```

The last command should list the `vector` extension.

Load the synthetic data and check it (see [data/seed/README.md](data/seed/README.md)):

```sh
python data/seed/seed.py | docker exec -i northstar-postgres psql -U northstar -d northstar
docker exec -i northstar-postgres psql -U northstar -d northstar < data/seed/verify.sql
```

From the host (pgAdmin, VS Code, Python), Postgres is on `localhost:5433` by default, so it
doesn't clash with a locally installed Postgres on 5432. Change it with `POSTGRES_PORT` in `.env`.

## CRM MCP server

Three read-only tools over Streamable HTTP (stateless) at `http://localhost:8001/mcp`:

| Tool | Returns |
|---|---|
| `search_accounts(query?, status?)` | Accounts the caller may see (max 50) |
| `get_account(account_id)` | One account; `notes` is marked untrusted |
| `list_contacts(account_id)` | The account's contacts, billing contact first |

Reps see only their own accounts, finance sees all, contractors are forbidden. Another user's
account looks exactly like a missing one. Until phase 5, identity comes from the `X-Dev-User`
(user UUID) and `X-Dev-Role` headers, accepted only when `CRM_DEV_AUTH=true`.

```sh
docker compose up -d mcp-crm                      # or: CRM_DEV_AUTH=true docker compose up -d mcp-crm
cd services/mcp-crm
uv run --env-file ../../.env pytest               # 33 tests; needs the seeded database
# identity tests (14) live in libs/northstar-common: cd libs/northstar-common && uv run pytest
uv run --env-file ../../.env python -m mcp_crm.server   # run without Docker
```

## Finance MCP server

At `http://localhost:8002/mcp` (`FIN_*` settings, `FIN_DEV_AUTH` for the dev headers):

| Tool | Who | Returns |
|---|---|---|
| `list_invoices(account_id?, status?)` | reps (own accounts), finance (all) | Up to 100 invoices, `truncated` if more |
| `get_invoice(invoice_id)` | reps (own accounts), finance (all) | One invoice, including `bank_ref` |
| `draft_credit_note(invoice_id, amount, reason)` | finance only | A credit note **pending approval**; nothing is issued |

Credit notes on an invoice can never add up to more than the invoice, even when two drafts
arrive at once (the invoice row is locked while checking). `bank_ref` is returned as stored:
the gateway redacts it before the LLM in phase 6, which is what the baseline-vs-secured
comparison shows.

```sh
docker compose up -d mcp-finance
cd services/mcp-finance && uv run --env-file ../../.env pytest   # 34 tests
```

## Email MCP server (mock)

At `http://localhost:8003/mcp` (`EMAIL_*` settings). `send_email(to, subject, body)` writes to
`email.outbox` and never really sends.

| Sender | May email |
|---|---|
| Sales rep | Internal staff, and contacts on accounts they own |
| Finance | Internal staff only |
| Contractor | Nobody |

Addresses are matched case-insensitively, and every refusal says the same thing
(`recipient not allowed`), so a reply can't reveal whose contact an address is. The recipient
must be one plain address and the subject a single line, which blocks header injection
(`...\nBcc: attacker@...`). Whether a recipient came from the user or from untrusted text is
checked by the gateway in phase 6.

```sh
docker compose up -d mcp-email
cd services/mcp-email && uv run --env-file ../../.env pytest   # 22 tests
```

## Knowledge MCP server

At `http://localhost:8004/mcp` (`KNOW_*` settings). `search_docs(query, k=5)` runs
**permission-aware hybrid search** in one SQL query:

1. keep only the documents the caller's role may read (`knowledge.document_access`)
2. rank them by meaning (pgvector cosine distance) and by keywords (Postgres full-text search)
3. merge the two rankings with reciprocal rank fusion and return the top `k`

Access is filtered *before* ranking, so unauthorised chunks never leave the database. Nobody can
read HR-confidential documents. Each result's content is marked untrusted. Embeddings come from
`BAAI/bge-small-en-v1.5` (384 dims) via `fastembed`, running locally; the image has the model
baked in and never downloads at runtime.

Documents must be ingested (chunked and embedded) after every reseed:

```sh
docker compose run --rm mcp-knowledge python -m mcp_knowledge.ingest   # or, without Docker:
cd services/mcp-knowledge && uv run --env-file ../../.env python -m mcp_knowledge.ingest
uv run --env-file ../../.env pytest                                     # 22 tests
```

Try any server with MCP Inspector (`npx @modelcontextprotocol/inspector@latest`): Streamable HTTP,
`http://localhost:8001/mcp`, headers `X-Dev-User: 5e1f0000-0000-4000-8000-000000000001` and
`X-Dev-Role: sales_rep` (rep1).

## Repo layout

```
secure-mcp-agent/
├── README.md
├── docker-compose.yml
├── .env.example
├── .gitignore
├── data/
│   ├── init/            # schema, run on first start
│   └── seed/            # deterministic synthetic data + verify.sql
├── docs/
│   ├── PROJECT_SPEC.md
│   └── adr/
├── libs/
│   └── northstar-common/  # identity, errors, settings, DB pool: shared by every server
├── services/
│   ├── agent/           # LangGraph agent API
│   ├── gateway/         # MCP gateway and security layers
│   ├── mcp-crm/         # done: 3 tools, 47 tests, Dockerfile
│   ├── mcp-finance/     # done: 3 tools, 34 tests, Dockerfile
│   ├── mcp-knowledge/   # done: hybrid search + ingestion, 22 tests, Dockerfile
│   └── mcp-email/       # done (mock): send_email, 22 tests, Dockerfile
├── evals/
│   ├── scenarios/
│   └── reports/
└── infra/               # Terraform, phase 8
```
