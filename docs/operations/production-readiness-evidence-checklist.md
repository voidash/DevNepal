# Production Readiness Evidence Checklist

**Requirements:** SRS §16.2, A10, SEC-013, NFR-DR-01, NFR-OBS-01, NFR-MNT-01

**Use:** Complete one signed release record for each production launch or material production
change. A check is complete only when its evidence is linked, dated, reviewed by its accountable
owner, and contains no unaccepted critical finding.

## Release Record

| Field | Value |
| --- | --- |
| Release identifier and commit | |
| Environment and planned release window | |
| Product owner | |
| Operations owner | |
| Security owner | |
| PMO approval reference | |
| Evidence repository or restricted ticket | |
| Residual risks accepted by and expiry | |

## Executable Repository Verification

Run these from the release commit. They verify code and tests only; they are not evidence of
production infrastructure, operational staffing, or external provider configuration.

```sh
uv run pytest
uv run pytest -m unit
uv run pytest tests/acceptance/
uv run ruff check .
uv run ruff format --check .
```

For GitHub pipeline behavior, also run:

```sh
uv run pytest apps/github_sync/tests/test_ingest.py apps/github_sync/tests/test_replay.py apps/github_sync/tests/test_process_pending.py apps/github_sync/tests/test_disconnect.py tests/acceptance/test_a09_github_outage_recovery.py
```

Record command output, revision, executor, UTC start/end, and failures. These commands do not
currently include an A10 acceptance test file; A10 is evidenced by the restore and incident drills
below.

## Evidence Gates

| Gate | Required evidence | Owner | Status |
| --- | --- | --- | --- |
| Business and pilot readiness | Signed scope, support model, policies, pilot ministries, success metrics, and contribution-ready projects with named maintainers and starter tasks | Product owner / PMO | Not started |
| Security delivery | Threat model, ASVS verification, dependency and secret scans, SBOM, CI release gate, independent penetration-test report, remediation or approved risk acceptance | Security owner | Not started |
| Privacy and legal | Privacy impact assessment, data inventory, notices, consent, records schedule, data-subject workflow, hosting and public-release approvals | Privacy/legal owner | Not started |
| Hosting and encryption | Approved government-controlled hosting, TLS, encrypted database/backups/object storage/secrets, named production access, and key-management review | Infrastructure owner | Not started |
| Observability and availability | Request and job correlation IDs, PII/secret filtering, dashboards, alert routing, health checks, worker monitoring, and 99.5% availability measurement plan | Operations owner | In progress — see docs/adr/0010-observability.md. Correlation IDs, log scrubbing, `/healthz`/`/readyz`, `/metrics` (HTTP, database, job, and queue metrics), worker-monitoring gauges, pending-migration tracking, and Grafana dashboards (HTTP, Database & Maintenance, Jobs & Maintenance, Availability, Executive Overview) implemented and verified locally. Alerting rules exist; Alertmanager routing, production deployment (gunicorn multiprocess wiring), and the 99.5% measurement plan are not started. |
| Backup and disaster recovery | Completed timed isolated restore drill meeting the PMO-approved RPO/RTO; encrypted database and object-store backup manifests; retained drill record | Operations and security | Not started |
| Incident response | Named roster, severity/on-call exercise, evidence-preservation exercise, provider-token containment exercise, communications approval, and post-incident review template | Security and operations | Not started |
| GitHub outage and replay | GitHub App approval, endpoint delivery evidence, worker supervision, signature-secret management, idempotency test, replay exercise, and implemented reconciliation test | GitHub integration owner | Blocked |
| Privileged access | First Super Admin controlled bootstrap record, named ministry officers, MFA enforcement, session revocation test, privileged access/export logs, and break-glass review | Security / PMO | Not started |
| Content, accessibility, and bilingual quality | WCAG 2.2 AA automated and manual audit, Nepali/English content QA, low-bandwidth/mobile review, content moderation and vulnerability-disclosure paths | Product / accessibility / community | Not started |
| Data and file safety | Object store private-by-default, signed access, malware-scanner quarantine drill, file type/size enforcement evidence, and recovery coverage of uploaded objects | Security / infrastructure | Not started |
| Maintainability and portability | Deployment artifacts, configuration inventory, migration/export procedure, owner roster, runbook review, and government-hosting migration rehearsal | Operations / PMO | Not started |
| Go/no-go | All critical gates complete, exceptions time-bound and approved, rollback authority and communication plan confirmed | PMO release authority | Not started |

## A10 Drill Evidence

Attach both records before marking the backup/DR and incident-response gates complete:

1. A restore exercise from `backup-restore-runbook.md` showing actual backup age, actual recovery
   time, database and object integrity checks, and pass/fail against approved RPO/RTO.
2. An incident exercise from `incident-response-runbook.md` showing severity assignment, on-call
   engagement, containment, evidence handling, recovery, communications decision, and post-review
   ownership.

## Known External Blocks At Document Creation

- PMO has not yet approved final RPO/RTO, records retention, hosting/data-residency, or the
  operational owner roster required by the SRS decision register.
- No infrastructure-as-code, deployment manifest, managed PostgreSQL backup configuration,
  object-store configuration, secret-store integration, or production access model exists
  in this repository. A local/dev Prometheus+Grafana stack exists (`ops/observability/`,
  docs/adr/0010-observability.md) but has not been deployed to any managed environment,
  has no Alertmanager routing, and has not been validated under a multi-process production
  WSGI server.
- The GitHub webhook receiver route, continuously running worker, GitHub App configuration,
  trusted timestamp design, and provider reconciliation client are not implemented here.
- The configured `GITHUB_TOKEN_PURGE` hook is only an integration seam; a real secret-store purge
  implementation and its operational evidence are required before GIT-011/SEC-013 containment is
  complete.

Do not approve production readiness by treating these missing external controls as documentation
exceptions. They are launch gates under SRS §16.2.
