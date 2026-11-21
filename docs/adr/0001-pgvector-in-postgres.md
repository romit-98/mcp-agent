# 0001: pgvector in Postgres instead of a separate vector database

Status: Accepted (2026-11-22)

## Context

The Knowledge server needs retrieval over about 60 documents: full-text search plus vector search.
Retrieval must be permission-aware (security rule 6): chunks a user may not read have to be
filtered out in SQL, under row-level security, *before* ranking, and must never leave the
database. v1 runs on a laptop in Docker Compose. Phase 8 moves to Azure on a small budget
(about US$5–25/month).

## Options

| Option | For | Against |
|---|---|---|
| **pgvector in the same Postgres** | Access filter, full-text and vector search in one SQL query under RLS. No extra service. Supported on Azure Database for PostgreSQL. | Search and transactional load share one instance. We build hybrid ranking (reciprocal rank fusion) ourselves. |
| Dedicated vector DB (Qdrant, Weaviate, Pinecone) | Built for vector search at scale, with rich filtering and hybrid search out of the box. | A second copy of the access rules that can drift from Postgres. Chunks are stored outside RLS. One more service to run, secure and pay for. |
| Azure AI Search | Managed hybrid search with security trimming. The natural path to scale on Azure. | Cloud only, so it doesn't fit laptop-first v1. Cost. Access filtering is done by the application, not the database. |

## Decision

Use pgvector (`pgvector/pgvector:pg17`, extension 0.8.x) inside the main Postgres database.
`knowledge.chunks` holds the embedding and a generated `tsvector`, and `knowledge.document_access`
holds the access rules. One query applies RLS, filters by access, runs both searches and merges
the results with reciprocal rank fusion.

## Consequences

Good:
- Unauthorised chunks are removed by the database itself, so a bug in the app code can't leak them.
- One source of truth. When a document is deleted, its chunks are deleted with it (`ON DELETE CASCADE`),
  so a stale copy can't stay searchable somewhere else.
- One less service locally and on Azure.

Bad:
- **Filtered vector search can return fewer than k results.** An approximate (HNSW) index finds
  nearest neighbours first and RLS filters afterwards, so a user with narrow access can get
  short or empty results. At about 60 documents we use exact search and this doesn't happen. At
  scale, use pgvector's iterative index scans or partial indexes per access group, and test for it.
- The embedding dimension is fixed per column. Changing embedding model means a migration and
  re-embedding everything.
- Retrieval and transactional queries compete for the same CPU and memory.

Revisit when: the corpus grows past roughly a million chunks, retrieval misses its p95 latency
target, or we move to multi-tenant. The scale-up path is Azure AI Search, with RLS-equivalent
security trimming tested by the same eval suite.
