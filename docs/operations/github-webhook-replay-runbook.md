# GitHub Webhook Replay Runbook

**Requirements:** GIT-004, GIT-005, GIT-006, GIT-012, NFR-PERF-03, A5, A9, SEC-013

**Status:** Design and verification runbook. It is not yet a live replay procedure because this
repository has no webhook URL route, worker process, GitHub App configuration, or implemented
provider reconciliation client.

## Current Implementation Boundary

The application service validates HMAC-SHA256 signatures, rejects timestamps outside a 300-second
window, records deduplication provenance, and processes `pending` rows through
`apps.github_sync.services.process_pending()`. It deduplicates first by GitHub delivery ID and
then by provider event ID. Processed events are not selected again.

The webhook view is currently empty, `config/urls.py` registers no webhook path, and
`reconcile()` returns `0` without calling GitHub. Consequently, do not represent GitHub console
redelivery, manual HTTP reposting, or reconciliation as working production recovery today.

## External Infrastructure Prerequisites

All items below must be complete before this can be used as an operational production runbook:

| Required input | Evidence needed |
| --- | --- |
| Registered GitHub App with least-privilege repository installations and subscribed events | App ID, approved permissions, installation inventory, and named owner |
| Public HTTPS webhook endpoint routed to a real receiver view | Endpoint deployment record and authenticated delivery test |
| High-entropy `GITHUB_WEBHOOK_SECRET` in managed secret storage | Secret reference, access audit, rotation procedure, and no plaintext value in evidence |
| A documented, authenticated source for the timestamp passed to replay-window validation | Threat-model approval. GitHub's normal webhook signature authenticates the body, not an arbitrary added timestamp header. |
| Continuously running, supervised worker that invokes `process_pending()` with metrics and alerts | Process definition, restart behavior, pending/failed age alerts, and named owner |
| GitHub API client and scheduled reconciliation implementation | Cursor, rate-limit/backoff, reconciliation-source ingestion, and recovery test proving GIT-006 |
| GitHub delivery-log access and approved incident evidence storage | Named access and retention policy |

## Triage

1. Open a restricted incident or operations ticket. Record the GitHub delivery ID, event type,
   repository ID or node ID, reported UTC time, correlation ID, and the reason for replay.
2. Search the `ProviderEvent` ledger by delivery ID and provider event ID. Preserve only the
   minimum necessary metadata; do not copy raw webhook bodies or private repository content into
   tickets.
3. Determine the state:

| Ledger state | Meaning | Action |
| --- | --- | --- |
| `processed` | Event was already handled | Do not replay for credit. Investigate downstream display or verification separately. |
| `duplicate` | A second delivery was safely recorded | No action unless the original row failed. |
| `pending` | Receipt succeeded but worker has not completed | Run or restore the worker, then monitor the existing row. |
| `failed` | Processing could not complete | Preserve `last_error`; fix the mapping or defect before an approved redelivery. Current code has no retry transition for failed rows. |
| `rejected` | Signature or replay-window validation failed | Treat as a security signal; do not bypass validation. |

## Executable Verification Commands

These commands exercise the current repository implementation without GitHub infrastructure:

```sh
uv run pytest apps/github_sync/tests/test_ingest.py apps/github_sync/tests/test_replay.py apps/github_sync/tests/test_dedup.py apps/github_sync/tests/test_process_pending.py
uv run pytest tests/acceptance/test_a09_github_outage_recovery.py
```

In an approved configured environment, the worker function itself is executable. This is
state-changing because it creates candidate contribution records for pending deliveries.

```sh
uv run manage.py shell -c 'from apps.github_sync.services import process_pending; print(process_pending(limit=50))'
```

The following command is read-only and provides a concise queue-health count:

```sh
uv run manage.py shell -c 'from apps.github_sync.models import ProviderEvent; from apps.github_sync.enums import ProcessingState; print({state: ProviderEvent.objects.filter(processing_state=state).count() for state in ProcessingState.values})'
```

## Future Live Replay Procedure

Perform these steps only after every prerequisite above is evidenced.

1. Confirm the original delivery is absent or failed for a remediated, mapped repository. Confirm
   the operation cannot create duplicate contribution or recognition credit.
2. Use GitHub's delivery log to redeliver the original event to the approved endpoint. Do not
   alter the body, signature, delivery identity, or required trusted timestamp metadata.
3. Confirm the receiver returns promptly, records a signature-valid `ProviderEvent`, and either
   collapses the delivery to the existing ledger row or safely records a duplicate.
4. Monitor the worker until the event is `processed` or has a documented failure. Check that the
   provider event and contribution provenance are unique and that the event is visible within the
   approved five-minute p95 objective under normal conditions.
5. If GitHub is unavailable, leave the public site available, keep queued work durable, and use
   the implemented reconciliation process only after it exists. Do not manufacture provider
   events from an unverified body.
6. Attach delivery IDs, ledger state transitions, correlation IDs, result, and any duplicate-proof
   query to the restricted ticket. Close only after the impact and any needed recognition reversal
   have been reviewed.

## Release Blockers

Until receiver routing, worker supervision, trusted timestamp design, GitHub App provisioning,
and reconciliation are implemented and tested in staging, the SRS §16.2 webhook-replay readiness
item is unresolved. The existing tests prove service behavior only; they do not prove a deployable
GitHub integration.
