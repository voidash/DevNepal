# ADR 0006: GitHub App integration and webhook pipeline

Date: 2026-09-03
Status: Accepted

## Context

DevNepal is a registry, not a code host (§1): verified contribution events must come from
authoritative GitHub activity (BR-006, GIT-007). GIT-001 (Must) mandates a registered
GitHub App with minimum permissions; GIT-004 (Must) mandates webhook subscriptions — not
polling — with every signature validated against a high-entropy secret; GIT-005 (Must)
requires webhook processing to be idempotent, queued, retryable, timestamped, and
protected against replay and duplicate delivery; GIT-012 (Must) requires each imported
event to retain provider event ID, repository ID, actor mapping, received time,
processing state, and verification provenance for audit and deduplication. GIT-006 (Must)
requires periodic reconciliation to recover missed webhooks within GitHub rate limits.
NFR-PERF-03 requires fast webhook acknowledgement with async processing (verified activity
visible within 5 min p95); A5 requires a duplicate delivery to create no duplicate
contribution; A9 requires a GitHub outage never to block public browsing (NFR-AVL-02).
GIT-010/GIT-011 require private data to stay private and revocation to stop sync and
delete tokens (AUTH-008: tokens never exposed to users or logs).

## Decision

- Single registered GitHub App, installed per repository selection (GIT-003), with the
  minimum permission set needed for the events in GIT-007 (pull-request merged, issue
  closed, approved review, release, qualifying default-branch commits); no full-history
  mirroring (§5.2, decision register).
- Webhook receiver (thin view) does exactly three things: validate the HMAC-SHA256
  signature in constant time against the configured high-entropy secret, reject stale
  timestamps (replay window), and persist the raw payload as a `ProviderEvent` row
  (UUID pk; unique constraint on provider event ID + delivery as dedup key), then ack.
  Duplicate deliveries collapse onto the existing row and return success (idempotent,
  GIT-005/A5).
- Processing happens **out of band**: a DB-backed pending-work queue drained by a worker
  loop, with per-event processing states (received → processing → succeeded / failed with
  retry + backoff). The queue abstraction is swappable for a real broker later; sync never
  touches the request path (A9, NFR-AVL-02). Only after successful processing does a
  candidate contribution record exist (BR-006).
- Reconciliation job (GIT-006): per-repository cursor sweep on a schedule, respecting
  rate limits, healing missed deliveries through the same ProviderEvent dedup path.
- Tokens/installs live in the repository connection record with sync state and health
  (§9.1); tokens are never logged and are deleted on disconnect/uninstall (GIT-011,
  AUTH-008), with the profile flipping to a disconnected state. Bot/automated actors and
  raw merge commits are filtered before any recognition credit (GIT-008, REC-006).

## Consequences

Positive: exactly-once contribution creation per provider event (A5); outage isolation
(A9); full provenance for every verified event (GIT-012, REC-001); least privilege by
construction (GIT-001, SEC-001).

Negative/risk: a worker process is a new operational component requiring monitoring
(sync-failure dashboards, ADM-006) and restart safety; signature-secret rotation must be
dual-accept across the window; the DB-backed queue is sufficient at pilot scale but must
be revisited if event volume or latency targets (NFR-PERF-03 p95) are missed.

Relevant SRS: §5.2, §9.1, §10, GIT-001–GIT-012, AUTH-008, BR-006, REC-001, REC-006,
NFR-PERF-03, NFR-AVL-02, SEC-001, SEC-006, A5, A9.
