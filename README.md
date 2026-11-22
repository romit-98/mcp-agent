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
- [ ] 2. CRM MCP server
- [ ] 3. Finance, Knowledge, Email servers
- [ ] 4. Insecure baseline agent
- [ ] 5. Identity (Keycloak)
- [ ] 6. Gateway and security layers
- [ ] 7. Eval harness and CI
- [ ] 8. Azure deployment

Definitions of done: [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md), section 8.

## Decision records

- [0001: pgvector in Postgres instead of a separate vector database](docs/adr/0001-pgvector-in-postgres.md)

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

## Repo layout

```
secure-mcp-agent/
├── README.md
├── docker-compose.yml
├── .env.example
├── .gitignore
├── data/
│   └── init/
│       └── 00-extensions.sql
├── docs/
│   ├── PROJECT_SPEC.md
│   └── adr/
├── services/
│   ├── agent/           # LangGraph agent API
│   ├── gateway/         # MCP gateway and security layers
│   ├── mcp-crm/
│   ├── mcp-finance/
│   ├── mcp-knowledge/
│   └── mcp-email/       # mock
├── evals/
│   ├── scenarios/
│   └── reports/
└── infra/               # Terraform, phase 8
```
