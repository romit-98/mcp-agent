# 0003: Local embeddings and permission-aware hybrid search

Status: Accepted (2026-11-24)

## Context

The Knowledge server answers questions from about 60 company documents. Security rule 6 says
retrieval must be filtered by access rights in SQL, under row-level security, before ranking,
and must never rely on the LLM to hide content. Scenario S3 tests exactly this: a contractor
asking about the refund policy must get the contractor-shared version and never the
finance-only one, even though both match the question well.

Two choices follow: which embedding model, and how to combine meaning-based and keyword search.

## Options: embeddings

| Option | For | Against |
|---|---|---|
| **bge-small-en-v1.5 via fastembed (local, ONNX)** | Free; nothing leaves the machine; the same text always gives the same vector (reproducible evals); no PyTorch, so a small image | Lower quality than large hosted models; CPU time per query |
| sentence-transformers (local, PyTorch) | Same models, widely used | Much larger image and slower builds |
| Hosted API (OpenAI / Azure OpenAI) | Higher quality, no local CPU | Data leaves the machine; needs a key; costs per call; the model can change under you |

## Options: ranking

| Option | For | Against |
|---|---|---|
| Vector only | Finds paraphrases | Misses exact terms, codes and acronyms ("BAS") |
| Full-text only | Exact and explainable | Misses paraphrases ("money back" vs "refund") |
| **Both, merged with reciprocal rank fusion (RRF)** | Gets both; RRF needs no score calibration between two very different scores | One more step in the query |

## Decision

- Embed with `BAAI/bge-small-en-v1.5` (384 dims) through `fastembed`, behind a small `Embedder`
  interface so a hosted provider can be swapped in later (phase 8). Queries and passages are
  embedded with the model's separate query and passage modes.
- One SQL query: `allowed` documents for the caller's role, then vector and full-text rankings
  over allowed chunks only, then RRF (`score = sum of 1 / (60 + rank)`), then the top k.
- No approximate (HNSW) index: at this size exact search is fast, and it keeps "filter, then
  rank" exact (see the trade-off in ADR 0001).
- The model is baked into the Docker image at build time; the container runs offline.
- Chunks are paragraphs packed up to 800 characters; the title is prepended before embedding.
  Every result is returned as untrusted text.

## Consequences

Good:
- Unauthorised chunks never leave the database; tests search every title as every role and find
  no forbidden document or canary.
- Retrieval sanity: all 55 documents finance can read are found by their own title in the top 3.
- Deterministic results keep the baseline-vs-secured evals comparable.

Bad:
- Chunks must be re-ingested after every reseed or model change.
- Changing to a model with a different dimension needs a schema migration and re-embedding.
- At much larger scale, exact search becomes slow; an HNSW index then needs care with
  filtering (iterative scans or per-access-group indexes) so results aren't silently short.

Revisit when: the corpus grows well beyond a few thousand chunks, or answer quality on the eval
set says a stronger model is worth sending data to a hosted provider.
