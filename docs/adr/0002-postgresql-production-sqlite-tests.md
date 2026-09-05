# ADR 0002: PostgreSQL in production, SQLite in tests

Date: 2026-09-03
Status: Accepted

## Context

Production needs: concurrent writers (webhook workers + request handlers, NFR-PERF-03),
JSONField querying (audit before/after payloads, §9.1), case-insensitive and fuzzy search
over Devanagari and Latin text (DSC-002, DSC-003, NFR-I18N-01), and JSON-aware indexing.
PostgreSQL's `pg_trgm` and full-text search cover Nepali (no stemmer exists; `simple`
dictionary still tokenizes Devanagari) without standing up a separate search engine.
PostgreSQL is open source and supportable in typical government/NITC-style hosting,
serving NFR-PORT-01 (migration to approved government-controlled environments).

Tests need to be fast, deterministic, and runnable anywhere (including offline agent
sandboxes) for the swarm's test-first contract to be practical. A per-test in-memory
SQLite database gives millisecond setup and trivial parallelism.

## Decision

- Production (and staging): PostgreSQL, selected in `config/settings/base.py` via
  `POSTGRES_*` environment variables.
- Tests: SQLite in-memory via `config/settings/test.py` (plus MD5 password hasher and
  locmem email for speed). Tests never require Docker or a running database server.
- Application code accesses the database only through the Django ORM — no raw,
  vendor-specific SQL in apps. Behavior must be identical on both backends.
- PostgreSQL-specific enhancements (e.g., `pg_trgm` GIN indexes for search, ADR 0009) live
  in migrations and are created conditionally on the vendor; tests exercise the common
  ORM paths (e.g., `icontains` fallback), and Postgres-only paths are additionally covered
  by integration tests when a Postgres instance is available.

## Consequences

Positive: fast, hermetic test runs keep the test-first workflow honest; production gets a
single robust relational engine with the search capabilities DSC-002/DSC-003 need; ops has
one stateful component to back up and restore (A10, NFR-DR-01).

Negative/risk: dialect drift — SQLite is permissive about constraints and transactions, so
a test can pass while Postgres behaves differently. Mitigated by keeping all constraints in
the ORM/model layer, avoiding vendor-specific SQL in app code, and treating any
Postgres-only bug as a signal to add a Postgres-backed integration test. The parity gap is
accepted and revisited if it produces escaped defects.

Relevant SRS: DSC-002, DSC-003, NFR-I18N-01, NFR-PERF-03, NFR-PORT-01, NFR-DR-01, A10.
