# ADR 0009: Search — ORM icontains now, Postgres trigram/FTS next, dedicated engine only on proven need

Date: 2026-09-03
Status: Accepted

## Context

DSC-002 (Must) requires search over title, summary, ministry, technology, skill,
contribution type, status, difficulty, effort, deadline, and language filters; DSC-003
(Must) requires Nepali Unicode search with stable slugs; NFR-I18N-01 requires Unicode
storage/search; §14.3 requires search to match Devanagari and Latin text "without
corrupting slugs, highlights, or sorting"; NFR-PERF-02 sets a p95 read target of 500 ms.

At launch the catalog is small: a pilot set of ministries and approved projects (§15.5 —
the platform must not even launch as an empty directory, but it is deliberately not
large). Operating Elasticsearch/Meilisearch/Typesearch infrastructure for a few thousand
rows is a direct cost against NFR-MNT-01 (maintainability by a small government team) and
NFR-PORT-01 (portable deployment), for relevance features nobody has yet demanded.
Search correctness for Nepali depends more on NFC normalization (ADR 0005) than on the
engine.

## Decision

- **Stage 1 (MVP)**: Django ORM `icontains` across the bilingual searchable fields
  (title/summary in en and ne, NFC-normalized per ADR 0005) combined with structured
  filter predicates for the DSC-002 facets. No search infrastructure.
- **Stage 2 (as data grows, Postgres-only)**: enable `pg_trgm` GIN indexes for fuzzy/
  partial matching on the same fields, and — if ranked results are needed — Postgres
  full-text search (`to_tsvector` with the `simple` configuration, since Nepali has no
  stemmer; `simple` still tokenizes Devanagari correctly). Both are in-database features
  of the production PostgreSQL choice (ADR 0002); no new deployable component.
- **Stage 3 (only on proven need)**: a dedicated search engine is introduced only when
  measured query latency breaches NFR-PERF-02 at p95 on production data, or facet/relevance
  requirements exceed what Postgres delivers. "Proven" means numbers, not anticipation.
- All search queries are built behind one query-builder seam in the owning app(s), so a
  later engine swap (Stage 3) touches one module plus an indexing path, not views.

## Consequences

Positive: zero search ops burden at launch; full DSC-002/DSC-003 compliance from Stage 1–2
on the existing database; reversible, data-driven escalation path.

Negative/risk: Stage 1 has no typo tolerance and ranking is implicit (recency/ordering
chosen per view); trigram paths are Postgres-only, so SQLite tests exercise the
`icontains` fallback and trigram behavior is covered by Postgres-backed integration runs
(ADR 0002); a Stage 3 migration would require a reindex and a new stateful component to
back up (NFR-DR-01) — accepted only with the evidence gate above.

Relevant SRS: DSC-002, DSC-003, §14.3, NFR-I18N-01, NFR-PERF-02, NFR-MNT-01, NFR-PORT-01,
NFR-DR-01, §15.5.
