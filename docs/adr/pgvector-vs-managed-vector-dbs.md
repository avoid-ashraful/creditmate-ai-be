# ADR: pgvector first for CreditMate semantic retrieval

Status: accepted (Stream C, plan §6). Date: 2026-11-11.

## Decision

Use **pgvector on the existing Postgres 17** for embedding storage and
ANN retrieval, integrated via the `pgvector` Python package
(`VectorField`, `CosineDistance`, HNSW index). Corpus: verified catalogue
products rendered to canonical text, chunked with field provenance.

## Why

- **Corpus size.** ~105 cards + ~220 other products today; even generous
  growth is 10^4–10^5 chunks. pgvector HNSW handles this easily.
- **Single-store consistency.** Embeddings live in the same database (and
  transaction family) as the products they describe. A verified product
  change and its re-embedding cannot drift across two systems.
- **SQL filters are the product requirement.** Retrieval must hard-filter
  by product type, bank and Islamic/conventional *before* ranking.
  In Postgres those are ordinary indexed predicates on the chunk rows.
- **Zero new infrastructure.** No extra service to deploy, back up,
  secure or pay for; the Helm/compose Postgres image simply becomes
  `pgvector/pgvector:pg17`.

## Alternatives considered

| Option | What would differ |
|---|---|
| **Pinecone** (managed) | Zero-ops ANN and excellent scaling, but per-vector pricing, data leaves Postgres (no transactional consistency with product rows), filters are metadata-sidecars rather than SQL, and another vendor/key/billing surface. A plus at billion-scale; irrelevant at 10^4–10^5 chunks. |
| **Weaviate** (self-hosted) | Strong built-in hybrid (BM25 + vector) and GraphQL API, but a whole new stateful service to operate, back up and upgrade, with its own consistency story next to Postgres. |
| **OpenSearch** (k-NN) | Would duplicate the operational burden of the existing Elasticsearch catalogue search, which already covers keyword search. Two search clusters for one small corpus is not justified. |

Boundary with existing search: Elasticsearch remains catalogue keyword
search; pgvector is semantic retrieval for grounding (advisor answers,
similar-product discovery). Neither replaces the other in this programme.

## Revisit trigger

Re-open this ADR when either is sustained in production-like measurement:
corpus > 1M chunks, **or** retrieval p95 > 150 ms at production traffic,
**or** a requirement appears that pgvector cannot express (e.g.
multi-region ANN). At that point Pinecone (managed) is the first
alternative to evaluate, with Weaviate if hybrid search must be unified.
