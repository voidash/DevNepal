# Incident Response Runbook

**Requirements:** SEC-013, SEC-002, SEC-008, GIT-011, NFR-OBS-01, A10

**Status:** Draft. The named on-call roster, communications channels, legal/privacy contacts,
and provider-secret operations are external inputs required before launch.

## Severity And Ownership

| Severity | Definition | Initial acknowledgement | Authority |
| --- | --- | --- | --- |
| SEV-1 | Confirmed or likely compromise of credentials, sensitive data, public-service availability, or active exploitation | 15 minutes | Incident commander may contain immediately |
| SEV-2 | Material security weakness, failed backup, persistent integration failure, or operational degradation without confirmed exposure | 1 hour | Incident commander coordinates remediation |
| SEV-3 | Limited, non-urgent defect or isolated failed job with a safe workaround | 1 business day | Service owner manages through normal operations |

The external on-call roster must name an incident commander, technical lead, security lead,
communications lead, privacy/legal contact, and service owners for hosting, PostgreSQL, object
storage, GitHub, identity providers, email, observability, and secret management. A person may
hold more than one role only if the PMO has accepted the coverage risk.

## External Infrastructure Prerequisites

The following controls cannot be created or verified by this repository:

- A 24-hour, authenticated incident channel and escalation roster.
- Restricted incident ticketing, evidence storage, and communications templates.
- Provider consoles and named break-glass access for hosting, PostgreSQL, object storage, GitHub
  App, identity providers, email, observability, and the secret store.
- Central log, metric, and trace retention with correlation-ID search and PII/secret filtering.
- A configured `GITHUB_TOKEN_PURGE` secret-store callable. Without it, the application records
  revocation but logs a warning and cannot demonstrate provider-token deletion.
- Approved legal/privacy notification thresholds, authority, recipients, and timelines.

## First Response

1. Open a restricted incident record. Record reporter, UTC detection time, reporter contact,
   affected services, initial severity, incident commander, and a new incident correlation ID.
2. Preserve evidence before making changes when doing so is safe: alert payloads, timestamps,
   request and background-job correlation IDs, audit-event IDs, provider delivery IDs, relevant
   configuration version IDs, and hashes of acquired artifacts. Never paste tokens, passwords,
   webhook secrets, full webhook bodies, private repository data, or personal data into broadly
   visible tickets.
3. Assess whether public browsing, privileged workflows, file uploads, GitHub synchronization,
   notifications, or identity are affected. Public browsing must remain isolated from GitHub
   outages where possible (ADR 0006, A9).
4. For SEV-1, contain first and notify the required security and PMO contacts in parallel. For
   SEV-2 and SEV-3, collect sufficient evidence before a disruptive change unless risk is rising.

## Containment

Use the least disruptive control that stops the harmful path. Record every action, actor, UTC
time, expected effect, and observed effect in the restricted incident record.

| Condition | Containment action |
| --- | --- |
| Suspected GitHub user-token compromise | Disconnect the affected DevNepal user connection and verify secret-store token purge. Stop affected repository synchronization if the scope is unclear. |
| GitHub App private-key, webhook-secret, or installation-token compromise | Disable or rotate the affected secret through the approved secret store; suspend or uninstall the affected GitHub App installation; rotate with an overlap plan only after security approval. |
| Webhook abuse or replay | Restrict the ingress path at the edge, preserve delivery IDs and signature results, and follow the webhook replay runbook. |
| Suspected data exposure | Remove public access at the hosting/object-store layer, preserve access logs, and engage privacy/legal immediately. |
| Malware or unsafe uploaded object | Quarantine the object at storage and scanning layers, preserve its hash and scan result, and prevent further downloads. |
| Availability incident | Enable documented graceful-degradation controls; avoid destructive database or queue actions until evidence is captured. |

### Executable Application Containment

The checked-in application can disconnect one affected user's GitHub connection. This command is
state-changing: run it only in the approved production access environment after recording the
target username and authorization. It writes an audit event, marks repositories activated by that
user as stopped, and invokes the configured token-purge hook.

```sh
uv run manage.py shell -c 'from apps.accounts.models import User; from apps.github_sync.services import disconnect; disconnect(User.objects.get(username="TARGET_USERNAME"))'
```

Verify the behavior without touching production through the existing executable test:

```sh
uv run pytest apps/github_sync/tests/test_disconnect.py
```

This command cannot revoke GitHub App installation credentials, rotate `GITHUB_WEBHOOK_SECRET`,
or remove a provider-side token unless the external secret-store purge hook and provider access
have been configured.

## Investigation, Recovery, And Communications

1. Correlate application and worker events using the durable `ProviderEvent.correlation_id` and
   append-only audit records. Treat audit rows as evidence; never bulk-update or delete them
   (ADR 0004).
2. Identify affected identities, repositories, projects, objects, records, and time window.
   Determine whether any contribution or recognition outcome needs a documented correction rather
   than a destructive deletion.
3. Eradicate the cause: patch or remove the vulnerable component, rotate affected credentials,
   revoke access, and validate authorization boundaries. Use a restore drill when integrity is in
   doubt; do not restore over production without the backup/restore authorization path.
4. Recover in a controlled order: secrets and access, infrastructure, PostgreSQL/object data,
   application instances, workers, then integrations. Confirm public traffic, privileged flows,
   background processing, and monitoring are healthy before closing containment.
5. The communications lead issues approved internal, ministry, user, and public notifications.
   Privacy/legal decides notification duties and content. Communications must describe known facts,
   protective actions, and a safe contact path without exposing investigative evidence.
6. Within five business days of SEV-1 or SEV-2 closure, hold a blameless post-incident review.
   Record timeline, impact, root cause, control failures, successful controls, corrective actions,
   owners, dates, and whether the runbook or readiness evidence needs revision.

## Exercise Evidence For A10

Exercise this runbook with security and operations contacts before launch. The record must show a
severity decision, on-call contact attempt, evidence preservation, at least one containment path,
recovery validation, communication decision, and post-incident review assignment. Link the
timed restore-drill record when the scenario includes data recovery.
