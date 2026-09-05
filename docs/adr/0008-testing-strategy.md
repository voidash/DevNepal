# ADR 0008: Testing strategy

Date: 2026-09-03
Status: Accepted

## Context

The SRS is the single source of truth, and its requirement IDs (AUTH-001, GOV-004,
GIT-005, A1–A10, …) are the mapping key between requirements, stories, tests, and code.
SEC-009 (Must) requires automated unit, integration, and authorization checks in CI;
NFR-MNT-01 requires the test suite to be one of the mechanisms that keeps the product
maintainable by government teams; §16 defines launch-critical end-to-end scenarios A1–A10
that must be demonstrably green. The build is executed by parallel agents (AGENTS.md), so
the test contract has to make "done" unambiguous: a behavior exists only when a test
citing its SRS requirement passes, and one agent's change may not break another's layer.

Fixture JSON decays silently and duplicates schema; hand-rolled setup functions in tests
drift. The suite must run fast and hermetically (ADR 0002) so test-first is actually
practiced, not skipped.

## Decision

- **Tooling**: pytest + pytest-django, factory-boy factories (`DjangoModelFactory`) in
  `apps/<app>/tests/factories.py`. No JSON fixtures, no hand-built ORM soup in tests.
  Strict markers (registered in `pyproject.toml`): `unit`, `integration`, `acceptance`,
  `github_webhook`.
- **Layers**:
  - *unit* (`apps/<app>/tests/test_*.py`, `-m unit`): services, models, normalization,
    state machine — fast, isolated, no cross-app side effects.
  - *integration* (same trees, `-m integration`): cross-app flows through services and
    the ORM (e.g., lifecycle + audit in one transaction).
  - *acceptance* (`tests/acceptance/test_aNN*.py`, `-m acceptance`): the SRS A1–A10
    end-to-end scenarios, each file mapped to its scenario ID and owned by the matching
    domain (e.g., `test_a01*` → accounts, `test_a09*` → github_sync).
- **SRS citation is mandatory**: every test's docstring names the requirement it
  verifies, e.g. `"""GOV-006: material edit returns published project to review."""`.
  Tests without a citation are deleted in review — they are either testing nothing the
  SRS asks for or mutating the contract.
- **Test-first workflow**: the failing test (with its SRS citation) is written before the
  behavior; the behavior is done when the new test and the full suite pass
  (`uv run pytest`), with `ruff check` and `ruff format` clean.
- Determinism rules: in-memory SQLite, MD5 password hasher, locmem email
  (`config/settings/test.py`); `USE_TZ` always on — tests construct aware datetimes.

## Consequences

Positive: every green test is traceable to a requirement, giving §16 acceptance a
machine-checkable basis; refactors are protected by the same map; parallel agents can
prove they broke nothing.

Negative/risk: browser-level accessibility audits (§16.2 WCAG audit) and penetration
testing (SEC-011) are out of this suite's scope and must be added as separate gates before
launch; acceptance tests are slower, so they are scoped to A1–A10 rather than every
feature. Marker discipline (correct layer tags) must be policed in review.

Relevant SRS: §16.1, §16.2, SEC-009, NFR-MNT-01, A1–A10.
